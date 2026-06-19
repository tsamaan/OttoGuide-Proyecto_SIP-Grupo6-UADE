from setuptools import setup
import os
from glob import glob

package_name = "ottoguide_unitree_capture_bridge"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", glob("launch/*.py")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="OttoGuide Team",
    maintainer_email="LucasCap12@users.noreply.github.com",
    description="Subscriber-only Unitree G1 DDS to ROS2 /unitree/* bridge",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            f"bridge_node = {package_name}.bridge_node:main",
        ],
    },
)
