#include <atomic>
#include <array>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <memory>
#include <stdexcept>
#include <string>
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
    frame_id_ = declare_parameter<std::string>("frame_id", "livox_frame");
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
    if (sdk_initialized_) {
      LivoxLidarSdkUninit();
      sdk_initialized_ = false;
    }
  }

private:
  static void point_cloud_callback(
    const uint32_t handle,
    const uint8_t dev_type,
    LivoxLidarEthernetPacket * data,
    void * client_data)
  {
    (void)handle;
    (void)dev_type;
    auto * node = static_cast<LivoxSdkBridgeNode *>(client_data);
    if (node != nullptr) {
      node->publish_point_cloud(data);
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
    if (node != nullptr) {
      node->publish_imu(data);
    }
  }

  void publish_point_cloud(const LivoxLidarEthernetPacket * packet)
  {
    if (!publish_pointcloud_ || !cloud_pub_ || packet == nullptr || packet->dot_num == 0) {
      return;
    }

    switch (packet->data_type) {
      case kLivoxLidarCartesianCoordinateHighData:
        publish_cartesian_points<LivoxLidarCartesianHighRawPoint>(
          packet, kMillimetersToMeters);
        break;
      case kLivoxLidarCartesianCoordinateLowData:
        publish_cartesian_points<LivoxLidarCartesianLowRawPoint>(
          packet, kCentimetersToMeters);
        break;
      default:
        RCLCPP_WARN_THROTTLE(
          get_logger(), *get_clock(), 5000,
          "Unsupported Livox point data_type=%u", packet->data_type);
        break;
    }
  }

  template<typename PointT>
  void publish_cartesian_points(const LivoxLidarEthernetPacket * packet, const double scale)
  {
    auto msg = sensor_msgs::msg::PointCloud2();
    msg.header.stamp = now();
    msg.header.frame_id = frame_id_;
    msg.height = 1;
    msg.width = packet->dot_num;
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
    modifier.resize(packet->dot_num);

    sensor_msgs::PointCloud2Iterator<float> iter_x(msg, "x");
    sensor_msgs::PointCloud2Iterator<float> iter_y(msg, "y");
    sensor_msgs::PointCloud2Iterator<float> iter_z(msg, "z");
    sensor_msgs::PointCloud2Iterator<float> iter_intensity(msg, "intensity");
    sensor_msgs::PointCloud2Iterator<uint8_t> iter_tag(msg, "tag");
    sensor_msgs::PointCloud2Iterator<uint8_t> iter_line(msg, "line");

    const auto * points = reinterpret_cast<const PointT *>(packet->data);
    for (uint16_t i = 0; i < packet->dot_num; ++i) {
      *iter_x = static_cast<float>(points[i].x * scale);
      *iter_y = static_cast<float>(points[i].y * scale);
      *iter_z = static_cast<float>(points[i].z * scale);
      *iter_intensity = static_cast<float>(points[i].reflectivity);
      *iter_tag = points[i].tag;
      *iter_line = 0;

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
        static_cast<unsigned>(packet->dot_num));
    }
  }

  void publish_imu(const LivoxLidarEthernetPacket * packet)
  {
    if (!publish_imu_ || !imu_pub_ || packet == nullptr) {
      return;
    }

    if (packet->data_type != kLivoxLidarImuData) {
      RCLCPP_WARN_THROTTLE(
        get_logger(), *get_clock(), 5000,
        "Ignoring non-IMU Livox data_type=%u in IMU callback", packet->data_type);
      return;
    }

    const auto * sample = reinterpret_cast<const LivoxLidarImuRawPoint *>(packet->data);
    auto msg = sensor_msgs::msg::Imu();
    msg.header.stamp = now();
    msg.header.frame_id = frame_id_;
    msg.orientation_covariance[0] = -1.0;
    msg.angular_velocity.x = sample->gyro_x;
    msg.angular_velocity.y = sample->gyro_y;
    msg.angular_velocity.z = sample->gyro_z;
    msg.linear_acceleration.x = sample->acc_x;
    msg.linear_acceleration.y = sample->acc_y;
    msg.linear_acceleration.z = sample->acc_z;
    imu_pub_->publish(msg);

    const auto count = ++imu_packets_published_;
    if (count % 100 == 0) {
      RCLCPP_INFO(
        get_logger(),
        "Published Livox IMU packets=%lu",
        static_cast<unsigned long>(count));
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
  std::atomic<uint64_t> cloud_packets_published_{0};
  std::atomic<uint64_t> imu_packets_published_{0};
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
