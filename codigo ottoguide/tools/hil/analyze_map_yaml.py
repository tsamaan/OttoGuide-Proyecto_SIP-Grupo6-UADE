import os
import sys
import yaml

def read_pgm(filename):
    with open(filename, 'rb') as f:
        # Read header
        header = f.readline().decode('ascii').strip()
        if header != 'P5':
            raise ValueError(f"Only P5 PGM format is supported, got {header}")

        # Skip comments
        while True:
            pos = f.tell()
            line = f.readline().decode('ascii')
            if not line.startswith('#'):
                f.seek(pos)
                break

        # Read width, height
        dims = f.readline().decode('ascii').split()
        width = int(dims[0])
        height = int(dims[1])

        # Read maxval
        maxval = int(f.readline().decode('ascii').strip())

        # Read pixel data
        data = f.read()

    return width, height, maxval, data

def analyze_map(yaml_path):
    if not os.path.exists(yaml_path):
        print(f"Error: {yaml_path} does not exist.")
        sys.exit(1)

    with open(yaml_path, 'r') as f:
        map_info = yaml.safe_load(f)

    image_name = map_info.get('image')
    if not image_name:
        print("Error: No 'image' field in yaml.")
        sys.exit(1)

    # Resolve image path relative to yaml file
    yaml_dir = os.path.dirname(os.path.abspath(yaml_path))
    image_path = os.path.join(yaml_dir, image_name)

    if not os.path.exists(image_path):
        print(f"Error: Image {image_path} does not exist.")
        sys.exit(1)

    resolution = map_info.get('resolution', 0.05)
    origin = map_info.get('origin', [0.0, 0.0, 0.0])
    occupied_thresh = map_info.get('occupied_thresh', 0.65)
    free_thresh = map_info.get('free_thresh', 0.25)

    try:
        width, height, maxval, data = read_pgm(image_path)
    except Exception as e:
        print(f"Error reading PGM: {e}")
        sys.exit(1)

    total_cells = width * height
    free_cells = 0
    occupied_cells = 0
    unknown_cells = 0

    min_x, min_y = width, height
    max_x, max_y = 0, 0

    for i in range(total_cells):
        val = data[i]
        # PGM values: 0 is black, 255 is white
        # According to ROS map_server:
        # p = (255 - val) / 255.0
        # If p > occupied_thresh -> occupied
        # If p < free_thresh -> free
        # Else -> unknown

        # Or often:
        # 205 (or around it) is unknown
        # 254/255 is free
        # 0 is occupied

        # Let's use standard ROS map_server logic
        p = (255.0 - val) / 255.0

        if p > occupied_thresh:
            occupied_cells += 1
            x = i % width
            y = i // width
            if x < min_x: min_x = x
            if x > max_x: max_x = x
            if y < min_y: min_y = y
            if y > max_y: max_y = y
        elif p < free_thresh:
            free_cells += 1
            x = i % width
            y = i // width
            if x < min_x: min_x = x
            if x > max_x: max_x = x
            if y < min_y: min_y = y
            if y > max_y: max_y = y
        else:
            unknown_cells += 1

    if occupied_cells == 0 and free_cells == 0:
        min_x, max_x, min_y, max_y = 0, 0, 0, 0

    bb_width = max_x - min_x + 1 if max_x >= min_x else 0
    bb_height = max_y - min_y + 1 if max_y >= min_y else 0

    physical_width = bb_width * resolution
    physical_height = bb_height * resolution

    report = f"""# Map Analysis Report

## Metadata
- **YAML Path**: `{os.path.abspath(yaml_path)}`
- **PGM Path**: `{os.path.abspath(image_path)}`

## Properties
- **Width**: {width} px
- **Height**: {height} px
- **Resolution**: {resolution} m/px
- **Origin**: {origin}
- **Occupied Threshold**: {occupied_thresh}
- **Free Threshold**: {free_thresh}

## Statistics
- **Total Cells**: {total_cells}
- **Free Cells**: {free_cells} ({(free_cells/total_cells)*100:.2f}%)
- **Occupied Cells**: {occupied_cells} ({(occupied_cells/total_cells)*100:.2f}%)
- **Unknown Cells**: {unknown_cells} ({(unknown_cells/total_cells)*100:.2f}%)

## Bounding Box (Useful Info)
- **Pixel Bounds**: X:[{min_x}, {max_x}], Y:[{min_y}, {max_y}]
- **Bounding Box Size**: {bb_width} x {bb_height} px
- **Approximate Physical Size**: {physical_width:.2f} x {physical_height:.2f} meters

## Notes
- **WARNING**: This map originates from a stationary bag file. It does not contain full navigation context.
- **LIMITATION**: This is NOT a definitive base for autonomous navigation. Use for preliminary offline testing and QA only.
"""
    print(report)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analyze_map_yaml.py <path_to_map.yaml>")
        sys.exit(1)
    analyze_map(sys.argv[1])
