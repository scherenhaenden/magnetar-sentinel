# 🚀 Magnetar Sentinel — Guía de Despliegue y Arquitectura en Producción

Esta carpeta contiene la arquitectura, plantillas de configuración y comandos de administración para el despliegue seguro de **Magnetar Sentinel** en el servidor.

---

## 🏗️ 1. Arquitectura de Seguridad

```
[ Internet ]
     │ HTTPS (Puerto 443)
     ▼
[ Nginx Reverse Proxy ] (sentinel.snippetandcode.com)
     │ Proxy local HTTP (127.0.0.1:5050)
     ▼
[ Gunicorn WSGI ] (2 workers)
     │ Carga /etc/magnetar/magnetar.env (Permisos 600)
     ▼
[ Flask App Engine (Magnetar Sentinel) ]
     ├── Base de datos: SQLite (/home/sc-sentinel/magnetar-sentinel/magnetar.db)
     └── Ingestión de Logs: Nginx logs locales / Fail2ban shield
```

---

## 🔒 2. Ubicación de Variables y Secretos

Para garantizar que ninguna contraseña ni dato sensible quede expuesto en Git o accesible vía web, las variables se gestionan a nivel del sistema operativo:

* **Ruta de Configuración en el Servidor:** `/etc/magnetar/magnetar.env`
* **Permisos Obligatorios:** `chmod 600 /etc/magnetar/magnetar.env` (Solo lectura para `root`)
* **Propietario:** `root:root`

### Variables Soportadas:
| Variable | Propósito | Ejemplo / Tipo |
| :--- | :--- | :--- |
| `MS_DASHBOARD_USER` | Usuario para HTTP Basic Auth | `admin` |
| `MS_DASHBOARD_PASS` | Contraseña para HTTP Basic Auth | *34+ caracteres seguros* |
| `MS_PORT` | Puerto interno de escucha | `5050` |
| `MS_DATABASE_URL` | URI de la base de datos | `sqlite:////home/sc-sentinel/magnetar-sentinel/magnetar.db` |
| `MS_GEOIP_DB` | Base de datos MaxMind GeoIP2 | `/usr/share/GeoIP/country.mmdb` |
| `MS_SSH_HOST` | Host para lectura de logs | `127.0.0.1` |
| `MS_SSH_USER` | Usuario para lectura de logs | `root` |
| `MS_SSH_KEY` | Llave SSH privada para logs | `/root/.ssh/id_ed25519` |
| `MS_LOG_DIR` | Directorio de logs de Nginx | `/home/<user>/logs/nginx` |
| `MS_DAYS` | Ventana de agregación de días | `7` |

---

## ⚙️ 3. Servicio Systemd

* **Archivo de Unidad:** `/etc/systemd/system/magnetar-sentinel.service`
* **Contenido de la Unidad:**
  ```ini
  [Unit]
  Description=Magnetar Sentinel Web Analytics Daemon
  After=network.target nginx.service

  [Service]
  Type=simple
  User=root
  WorkingDirectory=/home/sc-sentinel/magnetar-sentinel
  EnvironmentFile=/etc/magnetar/magnetar.env
  ExecStart=/home/sc-sentinel/magnetar-sentinel/.venv/bin/gunicorn -w 2 -b 127.0.0.1:5050 app:app
  Restart=always
  RestartSec=5s

  [Install]
  WantedBy=multi-user.target
  ```

---

## 🛠️ 4. Comandos de Mantenimiento y Operación

### Estado y Reinicio del Servicio
```bash
# Ver estado del servicio
sudo systemctl status magnetar-sentinel

# Reiniciar el servicio tras cambios
sudo systemctl restart magnetar-sentinel

# Ver logs en tiempo real
sudo journalctl -u magnetar-sentinel.service -f -n 50
```

### Actualización de Contraseña o Variables
```bash
# 1. Editar el archivo protegido
sudo nano /etc/magnetar/magnetar.env

# 2. Reiniciar el servicio para aplicar
sudo systemctl restart magnetar-sentinel
```

### Sincronización de Código desde Local
```bash
# Despliegue de cambios excluyendo entornos virtuales y bases de datos locales
rsync -avz --exclude='.venv' --exclude='.git' --exclude='magnetar.db' --exclude='__pycache__' \
    /ruta/local/magnetar-sentinel/ powersrv-root:/home/sc-sentinel/magnetar-sentinel/

# Reiniciar servicio
ssh powersrv-root "systemctl restart magnetar-sentinel"
```
