#include <atomic>
#include <array>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <deque>
#include <fstream>
#include <functional>
#include <iomanip>
#include <memory>
#include <mutex>
#include <new>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include "livox_lidar_api.h"

#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/imu.hpp"
#include "sensor_msgs/msg/point_cloud2.hpp"
#include "sensor_msgs/msg/point_field.hpp"
#include "sensor_msgs/point_cloud2_iterator.hpp"

namespace {

constexpr double kMillimetersToMeters = 0.001;
constexpr double kCentimetersToMeters = 0.01;
constexpr std::size_t kMaxLivoxPacketPayloadBytes = 1500;
constexpr std::size_t kDefaultMaxPointsPerPacket = 96;
constexpr std::size_t kMaxQueuedCloudFrames = 16;
constexpr std::size_t kMaxQueuedImuSamples = 256;
constexpr auto kPublishTimerPeriod = std::chrono::milliseconds(10);

bool file_exists(const std::string & path)
{
  std::ifstream stream(path.c_str());
  return stream.good();
}

std::string resolve_config_path(const std::string & path)
{
  const std::vector<std::string> candidates = {
    path,
    "../" + path,
    "../../" + path,
    "../../../" + path
  };

  for (const auto & candidate : candidates) {
    if (file_exists(candidate)) {
      return candidate;
    }
  }

  return path;
}

}  // namespace

class LivoxSdkBridgeNode : public rclcpp::Node
{
public:
  LivoxSdkBridgeNode()
  : Node("livox_sdk_bridge_node")
  {
    config_path_ = declare_parameter<std::string>(
      "config_path", "config/livox/mid360_sdk2_bridge.json");
    frame_id_ = declare_parameter<std::string>("frame_id", "utlidar_lidar");
    topic_cloud_ = declare_parameter<std::string>("topic_cloud", "/utlidar/cloud");
    topic_imu_ = declare_parameter<std::string>("topic_imu", "/livox/imu");
    publish_pointcloud_ = declare_parameter<bool>("publish_pointcloud", true);
    publish_imu_ = declare_parameter<bool>("publish_imu", true);
    debug_dry_run_no_publish_ = declare_parameter<bool>("debug_dry_run_no_publish", false);
    max_points_per_packet_ = declare_parameter<int>(
      "max_points_per_packet", static_cast<int>(kDefaultMaxPointsPerPacket));
    diagnostic_log_every_n_packets_ = declare_parameter<int>(
      "diagnostic_log_every_n_packets", 250);

    if (max_points_per_packet_ <= 0) {
      RCLCPP_WARN(
        get_logger(),
        "Invalid max_points_per_packet=%d; using default=%u",
        max_points_per_packet_,
        static_cast<unsigned>(kDefaultMaxPointsPerPacket));
      max_points_per_packet_ = static_cast<int>(kDefaultMaxPointsPerPacket);
    }
    if (diagnostic_log_every_n_packets_ <= 0) {
      diagnostic_log_every_n_packets_ = 250;
    }

    resolved_config_path_ = resolve_config_path(config_path_);
    if (!file_exists(resolved_config_path_)) {
      throw std::runtime_error("Livox SDK2 config_path does not exist: " + config_path_);
    }

    const auto qos = rclcpp::SensorDataQoS();
    if (publish_pointcloud_ && !debug_dry_run_no_publish_) {
      cloud_pub_ = create_publisher<sensor_msgs::msg::PointCloud2>(topic_cloud_, qos);
    }
    if (publish_imu_ && !debug_dry_run_no_publish_) {
      imu_pub_ = create_publisher<sensor_msgs::msg::Imu>(topic_imu_, qos);
    }
    publish_timer_ = create_wall_timer(
      kPublishTimerPeriod,
      std::bind(&LivoxSdkBridgeNode::publish_queued_messages, this));

    if (!LivoxLidarSdkInit(resolved_config_path_.c_str())) {
      throw std::runtime_error("LivoxLidarSdkInit failed for config_path: " + resolved_config_path_);
    }
    sdk_initialized_ = true;

    SetLivoxLidarPointCloudCallBack(&LivoxSdkBridgeNode::point_cloud_callback, this);
    SetLivoxLidarImuDataCallback(&LivoxSdkBridgeNode::imu_callback, this);

    if (!LivoxLidarSdkStart()) {
      LivoxLidarSdkUninit();
      sdk_initialized_ = false;
      throw std::runtime_error("LivoxLidarSdkStart failed");
    }

    RCLCPP_INFO(
      get_logger(),
      "Livox SDK2 bridge started: config=%s cloud=%s imu=%s frame_id=%s dry_run=%s max_points_per_packet=%d",
      resolved_config_path_.c_str(), topic_cloud_.c_str(), topic_imu_.c_str(), frame_id_.c_str(),
      debug_dry_run_no_publish_ ? "true" : "false", max_points_per_packet_);
  }

  ~LivoxSdkBridgeNode() override
  {
    accepting_callbacks_.store(false);
    if (sdk_initialized_) {
      LivoxLidarSdkUninit();
      sdk_initialized_ = false;
    }
    while (active_callbacks_.load() != 0) {
      std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
  }

private:
  class CallbackGuard
  {
  public:
    explicit CallbackGuard(LivoxSdkBridgeNode * node)
    : node_(nullptr)
    {
      if (node == nullptr || !node->accepting_callbacks_.load()) {
        return;
      }
      node->active_callbacks_.fetch_add(1);
      if (node->accepting_callbacks_.load()) {
        node_ = node;
      } else {
        node->active_callbacks_.fetch_sub(1);
      }
    }

    ~CallbackGuard()
    {
      if (node_ != nullptr) {
        node_->active_callbacks_.fetch_sub(1);
      }
    }

    explicit operator bool() const
    {
      return node_ != nullptr;
    }

  private:
    LivoxSdkBridgeNode * node_;
  };

  static void point_cloud_callback(
    const uint32_t handle,
    const uint8_t dev_type,
    LivoxLidarEthernetPacket * data,
    void * client_data)
  {
    (void)handle;
    (void)dev_type;
    auto * node = static_cast<LivoxSdkBridgeNode *>(client_data);
    CallbackGuard guard(node);
    if (guard) {
      try {
        node->enqueue_point_cloud(data);
      } catch (const std::bad_alloc & ex) {
        node->handle_bad_alloc("point_cloud_callback", data, ex);
      }
    }
  }

  static void imu_callback(
    const uint32_t handle,
    const uint8_t dev_type,
    LivoxLidarEthernetPacket * data,
    void * client_data)
  {
    (void)handle;
    (void)dev_type;
    auto * node = static_cast<LivoxSdkBridgeNode *>(client_data);
    CallbackGuard guard(node);
    if (guard) {
      try {
        node->enqueue_imu(data);
      } catch (const std::bad_alloc & ex) {
        node->handle_bad_alloc("imu_callback", data, ex);
      }
    }
  }

  struct CloudPoint
  {
    float x{0.0F};
    float y{0.0F};
    float z{0.0F};
    float intensity{0.0F};
    uint8_t tag{0};
    uint8_t line{0};
  };

  struct CloudFrame
  {
    std::vector<CloudPoint> points;
  };

  struct ImuSample
  {
    float gyro_x{0.0F};
    float gyro_y{0.0F};
    float gyro_z{0.0F};
    float acc_x{0.0F};
    float acc_y{0.0F};
    float acc_z{0.0F};
  };

  template<typename PointT>
  std::size_t max_safe_points_for_packet() const
  {
    const auto payload_limit = kMaxLivoxPacketPayloadBytes / sizeof(PointT);
    const auto configured_limit = static_cast<std::size_t>(max_points_per_packet_);
    return configured_limit < payload_limit ? configured_limit : payload_limit;
  }

  std::string packet_timestamp_hex(const LivoxLidarEthernetPacket * packet) const
  {
    if (packet == nullptr) {
      return "null";
    }

    std::ostringstream stream;
    stream << std::hex << std::setfill('0');
    for (const auto byte : packet->timestamp) {
      stream << std::setw(2) << static_cast<unsigned>(byte);
    }
    return stream.str();
  }

  void log_packet_diagnostic(
    const char * callback_name,
    const LivoxLidarEthernetPacket * packet,
    const char * action,
    const std::size_t max_safe_points)
  {
    RCLCPP_WARN_THROTTLE(
      get_logger(), *get_clock(), 2000,
      "%s Livox packet action=%s data_type=%u dot_num=%u max_safe_points=%u timestamp=%s",
      callback_name,
      action,
      packet == nullptr ? 0U : static_cast<unsigned>(packet->data_type),
      packet == nullptr ? 0U : static_cast<unsigned>(packet->dot_num),
      static_cast<unsigned>(max_safe_points),
      packet_timestamp_hex(packet).c_str());
  }

  void maybe_log_packet_sample(
    const char * callback_name,
    const LivoxLidarEthernetPacket * packet,
    const std::size_t max_safe_points)
  {
    const auto count = ++diagnostic_packets_seen_;
    if (count % static_cast<uint64_t>(diagnostic_log_every_n_packets_) != 0) {
      return;
    }

    RCLCPP_INFO(
      get_logger(),
      "%s Livox packet sample count=%lu data_type=%u dot_num=%u max_safe_points=%u timestamp=%s",
      callback_name,
      static_cast<unsigned long>(count),
      packet == nullptr ? 0U : static_cast<unsigned>(packet->data_type),
      packet == nullptr ? 0U : static_cast<unsigned>(packet->dot_num),
      static_cast<unsigned>(max_safe_points),
      packet_timestamp_hex(packet).c_str());
  }

  void handle_bad_alloc(
    const char * context,
    const LivoxLidarEthernetPacket * packet,
    const std::bad_alloc & ex)
  {
    ++bad_alloc_drops_;
    RCLCPP_ERROR_THROTTLE(
      get_logger(), *get_clock(), 2000,
      "Dropping Livox packet after std::bad_alloc in %s: %s data_type=%u dot_num=%u timestamp=%s bad_alloc_drops=%lu",
      context,
      ex.what(),
      packet == nullptr ? 0U : static_cast<unsigned>(packet->data_type),
      packet == nullptr ? 0U : static_cast<unsigned>(packet->dot_num),
      packet_timestamp_hex(packet).c_str(),
      static_cast<unsigned long>(bad_alloc_drops_.load()));
  }

  template<typename PointT>
  bool packet_dot_count_is_safe(const LivoxLidarEthernetPacket * packet) const
  {
    if (packet == nullptr || packet->dot_num == 0) {
      return false;
    }
    return packet->dot_num <= max_safe_points_for_packet<PointT>();
  }

  template<typename PointT>
  void enqueue_cartesian_points(const LivoxLidarEthernetPacket * packet, const double scale)
  {
    const auto max_safe_points = max_safe_points_for_packet<PointT>();
    if (!packet_dot_count_is_safe<PointT>(packet)) {
      log_packet_diagnostic("point_cloud_callback", packet, "drop_unsafe_dot_num", max_safe_points);
      ++cloud_packets_dropped_;
      return;
    }

    maybe_log_packet_sample("point_cloud_callback", packet, max_safe_points);

    if (debug_dry_run_no_publish_) {
      log_packet_diagnostic("point_cloud_callback", packet, "dry_run_drop", max_safe_points);
      ++cloud_packets_dropped_;
      return;
    }

    CloudFrame frame;
    frame.points.reserve(packet->dot_num);
    for (uint16_t i = 0; i < packet->dot_num; ++i) {
      PointT point{};
      std::memcpy(&point, packet->data + (i * sizeof(PointT)), sizeof(PointT));
      CloudPoint out;
      out.x = static_cast<float>(point.x * scale);
      out.y = static_cast<float>(point.y * scale);
      out.z = static_cast<float>(point.z * scale);
      out.intensity = static_cast<float>(point.reflectivity);
      out.tag = point.tag;
      frame.points.push_back(out);
    }

    std::lock_guard<std::mutex> lock(queue_mutex_);
    if (cloud_queue_.size() >= kMaxQueuedCloudFrames) {
      cloud_queue_.pop_front();
      ++cloud_packets_dropped_;
    }
    cloud_queue_.push_back(std::move(frame));
  }

  void enqueue_point_cloud(const LivoxLidarEthernetPacket * packet)
  {
    if (!publish_pointcloud_ || packet == nullptr || packet->dot_num == 0) {
      return;
    }

    switch (packet->data_type) {
      case kLivoxLidarCartesianCoordinateHighData:
        enqueue_cartesian_points<LivoxLidarCartesianHighRawPoint>(
          packet, kMillimetersToMeters);
        break;
      case kLivoxLidarCartesianCoordinateLowData:
        enqueue_cartesian_points<LivoxLidarCartesianLowRawPoint>(
          packet, kCentimetersToMeters);
        break;
      default:
        RCLCPP_WARN_THROTTLE(
          get_logger(), *get_clock(), 5000,
          "Unsupported Livox point data_type=%u", static_cast<unsigned>(packet->data_type));
        ++cloud_packets_dropped_;
        break;
    }
  }

  void publish_cloud_frame(const CloudFrame & frame)
  {
    if (!publish_pointcloud_ || debug_dry_run_no_publish_ || !cloud_pub_ || frame.points.empty()) {
      return;
    }

    auto msg = sensor_msgs::msg::PointCloud2();
    msg.header.stamp = now();
    msg.header.frame_id = frame_id_;
    msg.height = 1;
    msg.width = static_cast<uint32_t>(frame.points.size());
    msg.is_bigendian = false;
    msg.is_dense = true;

    sensor_msgs::PointCloud2Modifier modifier(msg);
    modifier.setPointCloud2Fields(
      6,
      "x", 1, sensor_msgs::msg::PointField::FLOAT32,
      "y", 1, sensor_msgs::msg::PointField::FLOAT32,
      "z", 1, sensor_msgs::msg::PointField::FLOAT32,
      "intensity", 1, sensor_msgs::msg::PointField::FLOAT32,
      "tag", 1, sensor_msgs::msg::PointField::UINT8,
      "line", 1, sensor_msgs::msg::PointField::UINT8);
    modifier.resize(frame.points.size());

    sensor_msgs::PointCloud2Iterator<float> iter_x(msg, "x");
    sensor_msgs::PointCloud2Iterator<float> iter_y(msg, "y");
    sensor_msgs::PointCloud2Iterator<float> iter_z(msg, "z");
    sensor_msgs::PointCloud2Iterator<float> iter_intensity(msg, "intensity");
    sensor_msgs::PointCloud2Iterator<uint8_t> iter_tag(msg, "tag");
    sensor_msgs::PointCloud2Iterator<uint8_t> iter_line(msg, "line");

    for (const auto & point : frame.points) {
      *iter_x = point.x;
      *iter_y = point.y;
      *iter_z = point.z;
      *iter_intensity = point.intensity;
      *iter_tag = point.tag;
      *iter_line = point.line;

      ++iter_x;
      ++iter_y;
      ++iter_z;
      ++iter_intensity;
      ++iter_tag;
      ++iter_line;
    }

    cloud_pub_->publish(msg);
    const auto count = ++cloud_packets_published_;
    if (count % 100 == 0) {
      RCLCPP_INFO(
        get_logger(),
        "Published Livox cloud packets=%lu last_points=%u",
        static_cast<unsigned long>(count),
        static_cast<unsigned>(frame.points.size()));
    }
  }

  void enqueue_imu(const LivoxLidarEthernetPacket * packet)
  {
    if (!publish_imu_ || packet == nullptr) {
      return;
    }

    if (packet->data_type != kLivoxLidarImuData) {
      RCLCPP_WARN_THROTTLE(
        get_logger(), *get_clock(), 5000,
        "Ignoring non-IMU Livox data_type=%u in IMU callback",
        static_cast<unsigned>(packet->data_type));
      ++imu_packets_dropped_;
      return;
    }

    const auto max_safe_points = max_safe_points_for_packet<LivoxLidarImuRawPoint>();
    if (!packet_dot_count_is_safe<LivoxLidarImuRawPoint>(packet)) {
      log_packet_diagnostic("imu_callback", packet, "drop_unsafe_dot_num", max_safe_points);
      ++imu_packets_dropped_;
      return;
    }

    maybe_log_packet_sample("imu_callback", packet, max_safe_points);

    if (debug_dry_run_no_publish_) {
      log_packet_diagnostic("imu_callback", packet, "dry_run_drop", max_safe_points);
      ++imu_packets_dropped_;
      return;
    }

    std::lock_guard<std::mutex> lock(queue_mutex_);
    for (uint16_t i = 0; i < packet->dot_num; ++i) {
      LivoxLidarImuRawPoint raw{};
      std::memcpy(&raw, packet->data + (i * sizeof(LivoxLidarImuRawPoint)), sizeof(raw));
      if (imu_queue_.size() >= kMaxQueuedImuSamples) {
        imu_queue_.pop_front();
        ++imu_packets_dropped_;
      }
      imu_queue_.push_back(ImuSample{raw.gyro_x, raw.gyro_y, raw.gyro_z, raw.acc_x, raw.acc_y, raw.acc_z});
    }
  }

  void publish_imu_sample(const ImuSample & sample)
  {
    if (!publish_imu_ || debug_dry_run_no_publish_ || !imu_pub_) {
      return;
    }

    auto msg = sensor_msgs::msg::Imu();
    msg.header.stamp = now();
    msg.header.frame_id = frame_id_;
    msg.orientation_covariance[0] = -1.0;
    msg.angular_velocity.x = sample.gyro_x;
    msg.angular_velocity.y = sample.gyro_y;
    msg.angular_velocity.z = sample.gyro_z;
    msg.linear_acceleration.x = sample.acc_x;
    msg.linear_acceleration.y = sample.acc_y;
    msg.linear_acceleration.z = sample.acc_z;
    imu_pub_->publish(msg);

    const auto count = ++imu_packets_published_;
    if (count % 100 == 0) {
      RCLCPP_INFO(
        get_logger(),
        "Published Livox IMU packets=%lu",
        static_cast<unsigned long>(count));
    }
  }

  void publish_queued_messages()
  {
    std::deque<CloudFrame> cloud_frames;
    std::deque<ImuSample> imu_samples;
    {
      std::lock_guard<std::mutex> lock(queue_mutex_);
      cloud_frames.swap(cloud_queue_);
      imu_samples.swap(imu_queue_);
    }

    for (const auto & frame : cloud_frames) {
      try {
        publish_cloud_frame(frame);
      } catch (const std::bad_alloc & ex) {
        handle_bad_alloc("publish_cloud_frame", nullptr, ex);
      }
    }
    for (const auto & sample : imu_samples) {
      try {
        publish_imu_sample(sample);
      } catch (const std::bad_alloc & ex) {
        handle_bad_alloc("publish_imu_sample", nullptr, ex);
      }
    }
  }

  std::string config_path_;
  std::string resolved_config_path_;
  std::string frame_id_;
  std::string topic_cloud_;
  std::string topic_imu_;
  bool publish_pointcloud_{true};
  bool publish_imu_{true};
  bool debug_dry_run_no_publish_{false};
  int max_points_per_packet_{static_cast<int>(kDefaultMaxPointsPerPacket)};
  int diagnostic_log_every_n_packets_{250};
  bool sdk_initialized_{false};
  std::atomic<bool> accepting_callbacks_{true};
  std::atomic<uint64_t> active_callbacks_{0};
  std::atomic<uint64_t> cloud_packets_published_{0};
  std::atomic<uint64_t> imu_packets_published_{0};
  std::atomic<uint64_t> cloud_packets_dropped_{0};
  std::atomic<uint64_t> imu_packets_dropped_{0};
  std::atomic<uint64_t> bad_alloc_drops_{0};
  std::atomic<uint64_t> diagnostic_packets_seen_{0};
  std::mutex queue_mutex_;
  std::deque<CloudFrame> cloud_queue_;
  std::deque<ImuSample> imu_queue_;
  rclcpp::TimerBase::SharedPtr publish_timer_;
  rclcpp::Publisher<sensor_msgs::msg::PointCloud2>::SharedPtr cloud_pub_;
  rclcpp::Publisher<sensor_msgs::msg::Imu>::SharedPtr imu_pub_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  try {
    rclcpp::spin(std::make_shared<LivoxSdkBridgeNode>());
  } catch (const std::exception & ex) {
    RCLCPP_FATAL(rclcpp::get_logger("livox_sdk_bridge_node"), "%s", ex.what());
    rclcpp::shutdown();
    return 1;
  }
  rclcpp::shutdown();
  return 0;
}
