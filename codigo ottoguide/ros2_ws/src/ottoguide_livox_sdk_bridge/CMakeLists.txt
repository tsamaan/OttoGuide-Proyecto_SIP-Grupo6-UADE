cmake_minimum_required(VERSION 3.5)
project(ottoguide_livox_sdk_bridge)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 14)
endif()

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)

find_path(LIVOX_SDK2_INCLUDE_DIR
  NAMES livox_lidar_api.h
  PATHS
    /home/unitree/Livox-SDK2/include
    /usr/local/include
)

find_library(LIVOX_SDK2_LIBRARY
  NAMES livox_lidar_sdk_shared
  PATHS
    /usr/local/lib
)

if(NOT LIVOX_SDK2_INCLUDE_DIR)
  message(FATAL_ERROR "Livox SDK2 header livox_lidar_api.h not found. Expected /home/unitree/Livox-SDK2/include or /usr/local/include on the robot.")
endif()

if(NOT LIVOX_SDK2_LIBRARY)
  message(FATAL_ERROR "Livox SDK2 shared library liblivox_lidar_sdk_shared.so not found. Expected /usr/local/lib on the robot.")
endif()

add_executable(livox_sdk_bridge_node
  src/livox_sdk_bridge_node.cpp
)

target_include_directories(livox_sdk_bridge_node PRIVATE
  ${LIVOX_SDK2_INCLUDE_DIR}
)

ament_target_dependencies(livox_sdk_bridge_node
  rclcpp
  sensor_msgs
)

target_link_libraries(livox_sdk_bridge_node
  ${LIVOX_SDK2_LIBRARY}
)

install(TARGETS livox_sdk_bridge_node
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY launch config
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
