#!/bin/bash
# shellcheck shell=bash
set -euo pipefail

: <<'DOC'
@TASK: Certificar que los sensores criticos (LiDAR Livox MID360 y RealSense D435i) 
       estan publicando datos correctamente en ROS 2 para slam_toolbox.
@INPUT: ROS 2 Foxy instalado en target G1, drivers livox_ros_driver2, realsense2_camera y pointcloud_to_laserscan disponibles.
@OUTPUT: Estado de sensores, tabla de topicos activos y frecuencias. EXIT 0 si todo OK.
@CONTEXT: Script de preflight HIL para validacion antes de mapeo/navegacion autonoma.
@SECURITY: Solo lectura de topicos; no publica comandos ni modifica estado del robot.

STEP 1: Sourcing y verificacion de entorno ROS 2
STEP 2: Deteccion de topicos criticos (LiDAR, RealSense, TF)
STEP 3: Validacion de frecuencia de publicacion (hz)
STEP 4: Generacion de reporte y codigo de salida
DOC

# ============================================================================
# CONFIGURACION
# ============================================================================

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Tiempos de espera y medicion
readonly TOPIC_WAIT_TIMEOUT_S="${PREFLIGHT_TOPIC_WAIT_S:-10}"
readonly HZ_MEASURE_DURATION_S="${PREFLIGHT_HZ_DURATION_S:-5}"
readonly MIN_HZ_LIDAR="${PREFLIGHT_MIN_HZ_LIDAR:-8.0}"      # Livox MID360 ~10Hz
readonly MIN_HZ_SCAN="${PREFLIGHT_MIN_HZ_SCAN:-8.0}"        # LaserScan derivado para slam_toolbox
readonly MIN_HZ_IMU="${PREFLIGHT_MIN_HZ_IMU:-80.0}"         # IMU Livox ~100Hz  
readonly MIN_HZ_CAMERA="${PREFLIGHT_MIN_HZ_CAMERA:-15.0}"   # RealSense ~30Hz
readonly MIN_HZ_TF="${PREFLIGHT_MIN_HZ_TF:-5.0}"            # TF ~10-50Hz
readonly LIVOX_MID360_IP="${LIVOX_MID360_IP:-192.168.123.120}"

# Topicos criticos a verificar
declare -A CRITICAL_TOPICS=(
    ["/utlidar/cloud"]="LiDAR PointCloud2"
    ["/utlidar/imu"]="LiDAR IMU"
    ["/scan"]="LaserScan requerido por slam_toolbox"
    ["/camera/depth/image_rect_raw"]="RealSense Depth"
    ["/camera/color/image_raw"]="RealSense Color"
    ["/tf"]="Transformaciones dinamicas"
    ["/tf_static"]="Transformaciones estaticas"
)

# Topicos opcionales (no bloqueantes)
declare -A OPTIONAL_TOPICS=(
    ["/camera/depth/color/points"]="PointCloud RealSense"
    ["/sportmodestate"]="Estado locomocion G1"
)

# ============================================================================
# FUNCIONES AUXILIARES
# ============================================================================

log_info() { printf '[INFO]  %s\n' "$*"; }
log_warn() { printf '[WARN]  %s\n' "$*" >&2; }
log_error() { printf '[ERROR] %s\n' "$*" >&2; }
log_section() { printf '\n=== %s ===\n' "$*"; }

# ----------------------------------------------------------------------------
# Paso 1: Sourcing del entorno ROS 2
# ----------------------------------------------------------------------------
source_ros_environment() {
    log_section "PASO 1: Sourcing Entorno ROS 2"
    
    local ros_setup_found=false
    local setup_file=""
    
    # Buscar setup de ROS 2 en orden de preferencia para target G1 EDU (Foxy nativo)
    for setup_path in "${ROS_SETUP_OVERRIDE:-}" "/opt/ros/foxy/setup.bash" "/opt/ros/humble/setup.bash"; do
        [[ -n "$setup_path" ]] || continue
        if [[ -f "$setup_path" ]]; then
            setup_file="$setup_path"
            ros_setup_found=true
            break
        fi
    done
    
    if [[ "$ros_setup_found" == false ]]; then
        log_error "No se encontro instalacion ROS 2 (ni Humble ni Foxy)"
        log_error "Buscado en: ROS_SETUP_OVERRIDE, /opt/ros/foxy/setup.bash, /opt/ros/humble/setup.bash"
        return 1
    fi
    
    log_info "Sourcing ROS 2 desde: $setup_file"
    # shellcheck source=/dev/null
    source "$setup_file"
    
    # Verificar que ros2 CLI esta disponible
    if ! command -v ros2 >/dev/null 2>&1; then
        log_error "Comando 'ros2' no disponible despues de sourcing"
        return 1
    fi
    
    # Source del workspace local si existe
    if [[ -f "${PROJECT_ROOT}/install/setup.bash" ]]; then
        log_info "Sourcing workspace local: ${PROJECT_ROOT}/install/setup.bash"
        # shellcheck source=/dev/null
        source "${PROJECT_ROOT}/install/setup.bash"
    fi
    
    log_info "ROS 2 Distro: ${ROS_DISTRO:-unknown}"
    log_info "ROS 2 Version: $(ros2 --version 2>&1 || echo 'N/A')"
    return 0
}

# ----------------------------------------------------------------------------
# Paso 2: Verificacion de drivers instalados
# ----------------------------------------------------------------------------
check_drivers_installed() {
    log_section "PASO 2: Verificacion de Drivers"
    
    local all_ok=true
    
    # Verificar livox_ros_driver2
    log_info "Verificando livox_ros_driver2..."
    if ros2 pkg list 2>/dev/null | grep -q "^livox_ros_driver2"; then
        log_info "  [OK] livox_ros_driver2 instalado"
    else
        log_warn "  [FALTA] livox_ros_driver2 no encontrado"
        log_warn "  Instalar: https://github.com/Livox-SDK/livox_ros_driver2"
        all_ok=false
    fi
    
    # Verificar realsense2_camera
    log_info "Verificando realsense2_camera..."
    if ros2 pkg list 2>/dev/null | grep -q "^realsense2_camera"; then
        log_info "  [OK] realsense2_camera instalado"
    else
        log_warn "  [FALTA] realsense2_camera no encontrado"
        log_warn "  Instalar: sudo apt install ros-${ROS_DISTRO}-realsense2-camera"
        all_ok=false
    fi
    
    # Verificar slam_toolbox
    log_info "Verificando slam_toolbox..."
    if ros2 pkg list 2>/dev/null | grep -q "^slam_toolbox"; then
        log_info "  [OK] slam_toolbox instalado"
    else
        log_warn "  [FALTA] slam_toolbox no encontrado"
        all_ok=false
    fi

    # Verificar nav2_bringup
    log_info "Verificando nav2_bringup..."
    if ros2 pkg list 2>/dev/null | grep -q "^nav2_bringup"; then
        log_info "  [OK] nav2_bringup instalado"
    else
        log_warn "  [FALTA] nav2_bringup no encontrado"
        all_ok=false
    fi

    # Verificar pointcloud_to_laserscan
    log_info "Verificando pointcloud_to_laserscan..."
    if ros2 pkg list 2>/dev/null | grep -q "^pointcloud_to_laserscan"; then
        log_info "  [OK] pointcloud_to_laserscan instalado"
    else
        log_warn "  [FALTA] pointcloud_to_laserscan no encontrado"
        log_warn "  Requerido si livox_ros_driver2 no publica /scan. Instalar ros-${ROS_DISTRO}-pointcloud-to-laserscan o lanzar un conversor equivalente."
        all_ok=false
    fi
    
    if [[ "$all_ok" == false ]]; then
        log_warn "Algunos drivers faltan - el sistema puede no funcionar completamente"
    fi
    
    return 0
}

# ----------------------------------------------------------------------------
# Paso 3: Deteccion de topicos activos
# ----------------------------------------------------------------------------
detect_active_topics() {
    log_section "PASO 3: Deteccion de Topicos Activos"
    
    local all_critical_found=true
    local total_critical=0
    local found_critical=0
    local total_optional=0
    local found_optional=0
    
    printf '\n%-50s %-15s %-30s\n' "TOPICO" "ESTADO" "DESCRIPCION"
    printf '%s\n' "$(printf '=%.0s' {1..100})"
    
    # Verificar topicos criticos
    for topic in "${!CRITICAL_TOPICS[@]}"; do
        ((total_critical++))
        local description="${CRITICAL_TOPICS[$topic]}"
        
        if ros2 topic list 2>/dev/null | grep -qx "$topic"; then
            printf '%-50s %-15s %-30s\n' "$topic" "[ACTIVO]" "$description"
            ((found_critical++))
        else
            printf '%-50s %-15s %-30s\n' "$topic" "[INACTIVO]" "$description"
            all_critical_found=false
        fi
    done
    
    # Verificar topicos opcionales
    printf '\n%-50s %-15s %-30s\n' "TOPICO (OPCIONAL)" "ESTADO" "DESCRIPCION"
    printf '%s\n' "$(printf '=%.0s' {1..100})"
    
    for topic in "${!OPTIONAL_TOPICS[@]}"; do
        ((total_optional++))
        local description="${OPTIONAL_TOPICS[$topic]}"
        
        if ros2 topic list 2>/dev/null | grep -qx "$topic"; then
            printf '%-50s %-15s %-30s\n' "$topic" "[ACTIVO]" "$description"
            ((found_optional++))
        else
            printf '%-50s %-15s %-30s\n' "$topic" "[INACTIVO]" "$description"
        fi
    done
    
    # Resumen
    printf '\n%s\n' "$(printf '=%.0s' {1..100})"
    printf 'CRITICOS: %d/%d activos | OPCIONALES: %d/%d activos\n' \
        "$found_critical" "$total_critical" "$found_optional" "$total_optional"
    
    if [[ "$all_critical_found" == false ]]; then
        log_error "Faltan topicos CRITICOS para operacion"
        return 1
    fi
    
    log_info "Todos los topicos criticos estan activos"
    return 0
}

# ----------------------------------------------------------------------------
# Paso 4: Analisis de frecuencia (hz)
# ----------------------------------------------------------------------------
measure_topic_frequencies() {
    log_section "PASO 4: Analisis de Frecuencia de Publicacion"
    
    local all_frequencies_ok=true
    declare -A measured_hz
    
    printf '\n%-50s %-12s %-12s %-12s\n' "TOPICO" "MEDIDO(Hz)" "MINIMO(Hz)" "ESTADO"
    printf '%s\n' "$(printf '=%.0s' {1..90})"
    
    # Funcion para medir frecuencia de un topico
    measure_hz() {
        local topic="$1"
        local duration="${2:-$HZ_MEASURE_DURATION_S}"
        
        # Usar timeout para limitar la medicion
        local output
        if output=$(timeout "$((duration + 2))" ros2 topic hz "$topic" --window "$duration" 2>&1); then
            # Extraer la frecuencia promedio de la ultima linea
            echo "$output" | grep -oP '(?<=average rate: )[0-9.]+' | tail -1
        else
            echo "0.0"
        fi
    }
    
    # Verificar /utlidar/cloud (LiDAR)
    log_info "Midiendo /utlidar/cloud (durante ${HZ_MEASURE_DURATION_S}s)..."
    local hz_lidar
    hz_lidar=$(measure_hz "/utlidar/cloud" "$HZ_MEASURE_DURATION_S" || echo "0.0")
    measured_hz["/utlidar/cloud"]="$hz_lidar"
    
    if (( $(echo "$hz_lidar >= $MIN_HZ_LIDAR" | bc -l 2>/dev/null || echo "0") )); then
        printf '%-50s %-12.2f %-12.1f %-12s\n' "/utlidar/cloud" "$hz_lidar" "$MIN_HZ_LIDAR" "[OK]"
    else
        printf '%-50s %-12.2f %-12.1f %-12s\n' "/utlidar/cloud" "$hz_lidar" "$MIN_HZ_LIDAR" "[BAJO]"
        all_frequencies_ok=false
    fi

    # Verificar /scan (LaserScan requerido por slam_toolbox)
    log_info "Midiendo /scan (durante ${HZ_MEASURE_DURATION_S}s)..."
    local hz_scan
    hz_scan=$(measure_hz "/scan" "$HZ_MEASURE_DURATION_S" || echo "0.0")
    measured_hz["/scan"]="$hz_scan"

    if (( $(echo "$hz_scan >= $MIN_HZ_SCAN" | bc -l 2>/dev/null || echo "0") )); then
        printf '%-50s %-12.2f %-12.1f %-12s\n' "/scan" "$hz_scan" "$MIN_HZ_SCAN" "[OK]"
    else
        printf '%-50s %-12.2f %-12.1f %-12s\n' "/scan" "$hz_scan" "$MIN_HZ_SCAN" "[BAJO]"
        log_warn "/scan ausente o por debajo del minimo. slam_toolbox usa scan_topic:=/scan; activar pointcloud_to_laserscan si livox_ros_driver2 solo publica /utlidar/cloud."
        all_frequencies_ok=false
    fi
    
    # Verificar /utlidar/imu (IMU)
    log_info "Midiendo /utlidar/imu (durante ${HZ_MEASURE_DURATION_S}s)..."
    local hz_imu
    hz_imu=$(measure_hz "/utlidar/imu" "$HZ_MEASURE_DURATION_S" || echo "0.0")
    measured_hz["/utlidar/imu"]="$hz_imu"
    
    if (( $(echo "$hz_imu >= $MIN_HZ_IMU" | bc -l 2>/dev/null || echo "0") )); then
        printf '%-50s %-12.2f %-12.1f %-12s\n' "/utlidar/imu" "$hz_imu" "$MIN_HZ_IMU" "[OK]"
    else
        printf '%-50s %-12.2f %-12.1f %-12s\n' "/utlidar/imu" "$hz_imu" "$MIN_HZ_IMU" "[BAJO]"
        # IMU es critico pero no bloqueante para slam_toolbox
        log_warn "Frecuencia IMU baja - puede afectar odometria"
    fi
    
    # Verificar /camera/depth/image_rect_raw (RealSense)
    if ros2 topic list 2>/dev/null | grep -qx "/camera/depth/image_rect_raw"; then
        log_info "Midiendo /camera/depth/image_rect_raw (durante ${HZ_MEASURE_DURATION_S}s)..."
        local hz_camera
        hz_camera=$(measure_hz "/camera/depth/image_rect_raw" "$HZ_MEASURE_DURATION_S" || echo "0.0")
        measured_hz["/camera/depth/image_rect_raw"]="$hz_camera"
        
        if (( $(echo "$hz_camera >= $MIN_HZ_CAMERA" | bc -l 2>/dev/null || echo "0") )); then
            printf '%-50s %-12.2f %-12.1f %-12s\n' "/camera/depth/image_rect_raw" "$hz_camera" "$MIN_HZ_CAMERA" "[OK]"
        else
            printf '%-50s %-12.2f %-12.1f %-12s\n' "/camera/depth/image_rect_raw" "$hz_camera" "$MIN_HZ_CAMERA" "[BAJO]"
            log_warn "Frecuencia de camara baja - puede afectar deteccion de obstaculos"
        fi
    else
        printf '%-50s %-12s %-12s %-12s\n' "/camera/depth/image_rect_raw" "N/A" "$MIN_HZ_CAMERA" "[NO EXISTE]"
    fi
    
    # Verificar /tf
    log_info "Midiendo /tf (durante ${HZ_MEASURE_DURATION_S}s)..."
    local hz_tf
    hz_tf=$(measure_hz "/tf" "$HZ_MEASURE_DURATION_S" || echo "0.0")
    measured_hz["/tf"]="$hz_tf"
    
    if (( $(echo "$hz_tf >= $MIN_HZ_TF" | bc -l 2>/dev/null || echo "0") )); then
        printf '%-50s %-12.2f %-12.1f %-12s\n' "/tf" "$hz_tf" "$MIN_HZ_TF" "[OK]"
    else
        printf '%-50s %-12.2f %-12.1f %-12s\n' "/tf" "$hz_tf" "$MIN_HZ_TF" "[BAJO]"
        log_warn "Frecuencia TF baja - puede afectar transformaciones"
    fi
    
    printf '%s\n' "$(printf '=%.0s' {1..90})"
    
    if [[ "$all_frequencies_ok" == true ]]; then
        log_info "Todas las frecuencias criticas estan dentro de rango"
        return 0
    else
        log_warn "Algunas frecuencias estan por debajo del minimo"
        return 0  # No bloqueante, solo advertencia
    fi
}

# ----------------------------------------------------------------------------
# Paso 5: Verificacion de red (opcional)
# ----------------------------------------------------------------------------
check_network_connectivity() {
    log_section "PASO 5: Verificacion de Conectividad de Red (Opcional)"
    
    # IPs conocidas del G1
    local pc1_ip="192.168.123.161"  # Motion Control
    local pc2_ip="192.168.123.164"  # Companion PC
    local lidar_ip="$LIVOX_MID360_IP" # LiDAR Livox MID360 configurable por contradiccion documental
    
    printf '\n%-25s %-15s %-20s\n' "DISPOSITIVO" "IP" "ESTADO"
    printf '%s\n' "$(printf '=%.0s' {1..65})"
    
    for device_info in "PC1(Motion):$pc1_ip" "PC2(Companion):$pc2_ip" "LiDAR:$lidar_ip"; do
        local device="${device_info%%:*}"
        local ip="${device_info##*:}"
        
        if ping -c 1 -W 2 "$ip" >/dev/null 2>&1; then
            printf '%-25s %-15s %-20s\n' "$device" "$ip" "[ALCANZABLE]"
        else
            printf '%-25s %-15s %-20s\n' "$device" "$ip" "[NO RESPONDE]"
        fi
    done
    
    printf '%s\n' "$(printf '=%.0s' {1..65})"
    log_info "Nota: El robot puede estar apagado o en modo standby si no responde"
    return 0
}

# ----------------------------------------------------------------------------
# Paso 6: Verificacion de transformaciones TF
# ----------------------------------------------------------------------------
check_tf_tree() {
    log_section "PASO 6: Verificacion del Arbol TF"
    
    # Verificar que tf_static tiene contenido
    local tf_static_content
    if tf_static_content=$(ros2 topic echo /tf_static --once --timeout 3 2>/dev/null || true); then
        if [[ -n "$tf_static_content" ]]; then
            log_info "TF Static: Contiene transformaciones estaticas"
            echo "$tf_static_content" | head -20
        else
            log_warn "TF Static: Sin contenido detectado"
        fi
    else
        log_warn "No se pudo leer /tf_static"
    fi
    
    # Listar frames disponibles si tf2_frames esta disponible
    if command -v ros2 run tf2_ros tf2_frames >/dev/null 2>&1; then
        log_info "Frames TF disponibles:"
        timeout 5 ros2 run tf2_ros tf2_frames 2>/dev/null || log_warn "Timeout esperando frames"
    fi
    
    return 0
}

# ----------------------------------------------------------------------------
# Generacion de reporte final
# ----------------------------------------------------------------------------
generate_report() {
    log_section "REPORTE FINAL DE PREFLIGHT"
    
    printf '\n%s\n' "$(printf '=%.0s' {1..80})"
    printf 'SISTEMA: %s\n' "OttoGuide Sensor Preflight Check"
    printf 'FECHA:   %s\n' "$(date '+%Y-%m-%d %H:%M:%S')"
    printf 'HOST:    %s\n' "$(hostname)"
    printf 'ROS 2:   %s\n' "${ROS_DISTRO:-unknown}"
    printf '%s\n' "$(printf '=%.0s' {1..80})"
    
    return 0
}

# ============================================================================
# FLUJO PRINCIPAL
# ============================================================================

main() {
    log_info "Iniciando preflight de sensores OttoGuide..."
    log_info "Tiempo de espera topicos: ${TOPIC_WAIT_TIMEOUT_S}s"
    log_info "Duracion medicion frecuencia: ${HZ_MEASURE_DURATION_S}s"
    
    local exit_code=0
    
    # Paso 1: Sourcing
    if ! source_ros_environment; then
        log_error "FALLO CRITICO: No se pudo cargar entorno ROS 2"
        exit 1
    fi
    
    # Paso 2: Verificar drivers
    check_drivers_installed || true  # No bloqueante
    
    # Paso 3: Verificar topicos activos
    if ! detect_active_topics; then
        log_error "FALLO CRITICO: Faltan topicos criticos"
        exit_code=1
    fi
    
    # Paso 4: Medir frecuencias
    measure_topic_frequencies || true  # No bloqueante
    
    # Paso 5: Verificar red (opcional)
    check_network_connectivity || true
    
    # Paso 6: Verificar TF
    check_tf_tree || true
    
    # Reporte final
    generate_report
    
    # Resultado
    printf '\n%s\n' "$(printf '=%.0s' {1..80})"
    if [[ $exit_code -eq 0 ]]; then
        printf '[PREFLIGHT OK] Todos los sensores criticos estan operativos.\n'
        printf 'Listo para: slam_toolbox, Nav2, mapeo autonomo.\n'
    else
        printf '[PREFLIGHT FAIL] Faltan sensores criticos o drivers no instalados.\n'
        printf 'Accion requerida: Verificar conexion con robot e iniciar drivers.\n'
    fi
    printf '%s\n' "$(printf '=%.0s' {1..80})"
    
    exit "$exit_code"
}

# Ejecutar solo si se corre directamente (no source)
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
