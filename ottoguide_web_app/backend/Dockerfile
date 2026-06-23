FROM python:3.11-slim AS builder

WORKDIR /app

# Instalar dependencias de sistema necesarias para compilar CycloneDDS
RUN apt-get update && apt-get install -y --no-install-recommends \
    cmake \
    gcc \
    g++ \
    make \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Compilar CycloneDDS desde source (fijado en 0.10.x para compatibilidad con unitree_sdk2py)
RUN git clone https://github.com/eclipse-cyclonedds/cyclonedds -b releases/0.10.x /opt/cyclonedds \
    && cd /opt/cyclonedds && mkdir build install && cd build \
    && cmake .. -DCMAKE_INSTALL_PREFIX=/opt/cyclonedds/install \
    && cmake --build . --target install

ENV CYCLONEDDS_HOME=/opt/cyclonedds/install

# Instalar unitree_sdk2py desde el repo oficial
RUN git clone https://github.com/unitreerobotics/unitree_sdk2_python.git /opt/unitree_sdk2py \
    && cd /opt/unitree_sdk2py \
    && pip install --no-cache-dir .

# Instalar las dependencias de Python del proyecto (fastapi, uvicorn, etc.)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# ── Imagen final (slim) ──
FROM python:3.11-slim

WORKDIR /app

# Copiar site-packages y ejecutables (como uvicorn) del builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copiar las librerias compiladas de CycloneDDS del builder
COPY --from=builder /opt/cyclonedds/install /opt/cyclonedds/install

# Setear variables de entorno para que el SDK encuentre CycloneDDS en runtime
ENV CYCLONEDDS_HOME=/opt/cyclonedds/install
ENV LD_LIBRARY_PATH=/opt/cyclonedds/install/lib:$LD_LIBRARY_PATH

# Copiar el codigo de la app
COPY app ./app

EXPOSE 3000

# Servidor ASGI. Escucha en todas las interfaces para ser accesible por RJ45.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3000"]
