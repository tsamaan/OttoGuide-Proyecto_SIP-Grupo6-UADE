#include <atomic>
#include <array>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <deque>
#include <fstream>
#include <functional>
#include <memory>
#include <mutex>
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

    resolved_config_path_ = resolve_config_path(config_path_);
    if (!file_exists(resolved_config_path_)) {
      throw std::runtime_error("Livox SDK2 config_path does not exist: " + config_path_);
    }

    const auto qos = rclcpp::SensorDataQoS();
    if (publish_pointcloud_) {
      cloud_pub_ = create_publisher<sensor_msgs::msg::PointCloud2>(topic_cloud_, qos);
    }
    if (publish_imu_) {
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

    RCLCPP_INFO(get_logger(), "Livox SDK2 bridge started: config=%s cloud=%s imu=%s frame_id=%s",
      resolved_config_path_.c_str(), topic_cloud_.c_str(), topic_imu_.c_str(), frame_id_.c_str());
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
      node->enqueue_point_cloud(data);
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
      node->enqueue_imu(data);
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
  bool packet_dot_count_is_safe(const LivoxLidarEthernetPacket * packet) const
  {
    if (packet == nullptr || packet->dot_num == 0) {
      return false;
    }
    const auto max_dots = kMaxLivoxPacketPayloadBytes / sizeof(PointT);
    return packet->dot_num <= max_dots;
  }

  template<typename PointT>
  void enqueue_cartesian_points(const LivoxLidarEthernetPacket * packet, const double scale)
  {
    if (!packet_dot_count_is_safe<PointT>(packet)) {
      RCLCPP_WARN_THROTTLE(
        get_logger(), *get_clock(), 5000,
        "Dropping Livox cloud packet with unsafe dot_num=%u for data_type=%u",
        packet == nullptr ? 0U : static_cast<unsigned>(packet->dot_num),
        packet == nullptr ? 0U : static_cast<unsigned>(packet->data_type));
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
    if (!publish_pointcloud_ || !cloud_pub_ || packet == nullptr || packet->dot_num == 0) {
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
    if (!publish_pointcloud_ || !cloud_pub_ || frame.points.empty()) {
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
    if (!publish_imu_ || !imu_pub_ || packet == nullptr) {
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

    if (!packet_dot_count_is_safe<LivoxLidarImuRawPoint>(packet)) {
      RCLCPP_WARN_THROTTLE(
        get_logger(), *get_clock(), 5000,
        "Dropping Livox IMU packet with unsafe dot_num=%u",
        static_cast<unsigned>(packet->dot_num));
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
    if (!publish_imu_ || !imu_pub_) {
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
      publish_cloud_frame(frame);
    }
    for (const auto & sample : imu_samples) {
      publish_imu_sample(sample);
    }
  }

  std::string config_path_;
  std::string resolved_config_path_;
  std::string frame_id_;
  std::string topic_cloud_;
  std::string topic_imu_;
  bool publish_pointcloud_{true};
  bool publish_imu_{true};
  bool sdk_initialized_{false};
  std::atomic<bool> accepting_callbacks_{true};
  std::atomic<uint64_t> active_callbacks_{0};
  std::atomic<uint64_t> cloud_packets_published_{0};
  std::atomic<uint64_t> imu_packets_published_{0};
  std::atomic<uint64_t> cloud_packets_dropped_{0};
  std::atomic<uint64_t> imu_packets_dropped_{0};
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
