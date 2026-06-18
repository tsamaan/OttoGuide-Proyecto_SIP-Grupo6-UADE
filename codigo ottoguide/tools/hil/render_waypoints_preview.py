import os
import sys
import yaml
import math

def read_pgm(filename):
    with open(filename, 'rb') as f:
        header = f.readline().decode('ascii').strip()
        if header != 'P5':
            raise ValueError(f"Only P5 PGM format is supported, got {header}")

        while True:
            pos = f.tell()
            line = f.readline().decode('ascii')
            if not line.startswith('#'):
                f.seek(pos)
                break

        dims = f.readline().decode('ascii').split()
        width = int(dims[0])
        height = int(dims[1])
        maxval = int(f.readline().decode('ascii').strip())
        data = bytearray(f.read())

    return width, height, maxval, data

def write_pgm(filename, width, height, maxval, data):
    with open(filename, 'wb') as f:
        f.write(f"P5\n{width} {height}\n{maxval}\n".encode('ascii'))
        f.write(data)

def draw_point(data, width, height, cx, cy, radius=2, color=0):
    for y in range(max(0, cy - radius), min(height, cy + radius + 1)):
        for x in range(max(0, cx - radius), min(width, cx + radius + 1)):
            if (x - cx)**2 + (y - cy)**2 <= radius**2:
                data[y * width + x] = color

def render_preview(map_yaml, waypoints_yaml):
    if not os.path.exists(map_yaml):
        print(f"Error: Map YAML {map_yaml} not found.")
        sys.exit(1)

    if not os.path.exists(waypoints_yaml):
        print(f"Error: Waypoints YAML {waypoints_yaml} not found.")
        sys.exit(1)

    with open(map_yaml, 'r') as f:
        map_info = yaml.safe_load(f)

    with open(waypoints_yaml, 'r') as f:
        waypoints_info = yaml.safe_load(f)

    image_name = map_info.get('image')
    yaml_dir = os.path.dirname(os.path.abspath(map_yaml))
    image_path = os.path.join(yaml_dir, image_name)

    resolution = map_info.get('resolution', 0.05)
    origin = map_info.get('origin', [0.0, 0.0, 0.0])

    try:
        width, height, maxval, data = read_pgm(image_path)
    except Exception as e:
        print(f"Error reading PGM: {e}")
        sys.exit(1)

    waypoints_to_draw = []
    missing_coords = False

    for wp in waypoints_info.get('waypoints', []):
        pose = wp.get('pose', {})
        x = pose.get('x')
        y = pose.get('y')

        if x is None or y is None:
            missing_coords = True
            print(f"Waypoint '{wp.get('id')}' is missing x or y coordinates. (Values are null)")
        else:
            # Convert world coordinates to map pixels
            # Map origin is lower-left corner of image
            # Wait, standard ROS map: origin is world coordinates of the lower-left pixel (0, height-1).
            # Actually, standard ROS map: pixel (0,0) is lower-left or upper-left?
            # Standard map_server: Origin is the real-world pose of the cell (0,0) which is lower-left.
            # Usually image (0,0) is top-left in PGM.
            # px = (x - origin_x) / resolution
            # py = height - (y - origin_y) / resolution

            px = int((x - origin[0]) / resolution)
            py = height - int((y - origin[1]) / resolution) - 1

            if 0 <= px < width and 0 <= py < height:
                waypoints_to_draw.append((wp.get('id'), px, py))
            else:
                print(f"Waypoint '{wp.get('id')}' is out of map bounds.")

    if missing_coords and not waypoints_to_draw:
        print("\nReport: Waypoints template only contains null coordinates. No points to render.")
        print("A base image preview was NOT generated since there are no valid points.")
        return

    # Draw waypoints
    for wid, px, py in waypoints_to_draw:
        draw_point(data, width, height, px, py, radius=2, color=0) # Draw black circle

    out_file = os.path.join(yaml_dir, "waypoints_preview.pgm")
    write_pgm(out_file, width, height, maxval, data)
    print(f"\nRendered {len(waypoints_to_draw)} waypoints to {out_file}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python render_waypoints_preview.py <path_to_map.yaml> <path_to_waypoints.yaml>")
        sys.exit(1)
    render_preview(sys.argv[1], sys.argv[2])
