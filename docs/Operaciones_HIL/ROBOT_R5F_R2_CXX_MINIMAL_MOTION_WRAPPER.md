# ROBOT-R5F-R2 -- Wrapper minimo C++ de movimiento G1

## Objetivo

Resolver el bloqueo identificado en ROBOT-R5F-R1 (`SAFE_MOTION_WRAPPER_FOUND = false`):
OttoGuide no tenia ningun wrapper propio, acotado y auditado, para mover el robot Unitree
G1 EDU 8. Este documento describe el wrapper minimo construido y validado en R5F-R2.

## API utilizada

`unitree::robot::g1::LocoClient`
(`unitree_sdk2/include/unitree/robot/g1/loco/g1_loco_client.hpp`), la API oficial y especifica
de Unitree para locomocion de G1 -- confirmada por lectura directa del SDK ya instalado en el
companion computer del robot, no un ejemplo generico de otro modelo (B2/Go2/A2).

## Binario y modos

`ottoguide_g1_micro_motion.cpp` expone 3 modos por linea de comandos:

- `--mode=stop` (default): llama solo `LocoClient::Damp()` (equivalente a `SetFsmId(1)`,
  estado pasivo/amortiguado). Nunca mueve el robot.
- `--mode=micro-yaw`: `SetVelocity(vx=0, vy=0, omega=0.08 rad/s, duration=0.30s)`, seguido
  siempre de `Damp()` incondicional.
- `--mode=linear-min`: `SetVelocity(vx=0.05 m/s, vy=0, omega=0, duration=0.30s)`, seguido
  siempre de `Damp()` incondicional.

Los limites (duracion, magnitud) estan hardcodeados como constantes `constexpr` en el
binario, no son configurables via CLI -- decision deliberada para que no sea posible invocar
el binario con una magnitud mayor por error.

## Build

```bash
./build_g1_micro_motion.sh [output_path]
```

Requiere el SDK de Unitree instalado (`/opt/unitree_robotics` por defecto, override via
`OTTOGUIDE_UNITREE_SDK_ROOT`). Validado con g++ 9.4.0 sobre Ubuntu 20.04 aarch64 en el
companion computer real del robot (192.168.123.164). Dependencias del SDK
(`libunitree_sdk2.a`, `libddsc`, `libddscxx`) ya estaban presentes system-wide; no se
requirio `sudo` ni instalar nada adicional durante la validacion de R5F-R2.

## Resultados de validacion (R5F-R2)

- Build: exitoso (exit 0).
- `--mode=stop` sobre la interfaz de red fisica real (`eth0`, no loopback): exitoso,
  `Damp()` retorno codigo 0 contra el servicio de locomocion real del robot.
- `--mode=micro-yaw` y `--mode=linear-min`: implementados y compilados, pero **no
  ejecutados** en R5F-R2 -- el operador no autorizo el movimiento fisico en la fase de
  confirmacion correspondiente. Quedan pendientes de una futura sesion HIL supervisada con
  autorizacion explicita.

## Bug encontrado y corregido durante la validacion

El parser de argumentos tenia un offset fijo incorrecto al extraer el valor del flag de
interfaz de red (`--network_interface=`), cortando un caracter de mas y convirtiendo
`eth0` en `th0` (interfaz inexistente). Esto producia un fallo de inicializacion del canal
DDS que, en un primer analisis, parecia ser un timeout del servicio remoto de locomocion
(codigo de error 3104, `UT_ROBOT_ERR_CLIENT_API_TIMEOUT`) en vez del bug de parsing real.
Se corrigio calculando el offset con `std::string(...).size()` en tiempo de compilacion en
vez de un numero magico, eliminando la clase de bug. Tras el fix, `--network_interface=eth0`
funciono correctamente.

## Notas de red

El servicio de locomocion del robot **no** responde sobre la interfaz de loopback (`lo`) del
companion computer -- debe usarse la interfaz fisica real (`eth0` en el companion validado)
para que el canal DDS alcance el servicio real del robot.

## Limitaciones

- Solo cubre `Damp()`, `SetVelocity()` (yaw puro o desplazamiento lineal puro). No cubre
  otros modos de la API (`StandUp`, `Squat`, `BalanceStand`, brazos, manos, etc.).
- No incluye deteccion de caida ni lectura de estado de balance -- depende enteramente de la
  supervision humana y del propio controlador interno del robot para la seguridad durante el
  movimiento.
- Los limites de magnitud (0.08 rad/s, 0.05 m/s) y duracion (0.30s) fueron elegidos como
  valores conservadores de partida, no derivados de un analisis formal de los limites
  maximos seguros del G1 EDU 8 -- deberian revisarse antes de cualquier uso mas alla de
  pruebas HIL supervisadas.

## Proximo paso recomendado

Ejecutar una sesion HIL dedicada (con las mismas confirmaciones explicitas separadas para
micro-yaw y linear-min) donde el operador autorice el movimiento, para completar la
validacion fisica end-to-end que R5F-R2 dejo pendiente.
