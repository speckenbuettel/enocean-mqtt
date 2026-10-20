# Docker installation

The image `senecaiii/enocean-mqtt` supports Linux AMD64 and ARM64, including
Raspberry Pi with a 64-bit operating system. A USB adapter is optional for replay
and API exploration. Native installation remains supported.

## 1. Prepare a deployment directory

Install Docker Engine and the Compose plugin on your Linux host first. Download
`compose.yaml` from this repository into an empty deployment directory. Also
download `compose.usb.yaml` if USB access is required. Keep this directory separate
from a source checkout to avoid mixing deployment files with application sources.

```sh
mkdir -p enocean-mqtt/config enocean-mqtt/data enocean-mqtt/export
cd enocean-mqtt
chmod 700 config data export
export LOCAL_UID="$(id -u)"
export LOCAL_GID="$(id -g)"
docker compose pull
docker compose run --rm --no-deps enocean-mqtt init
```

Run these commands as the same user that owns the deployment directories. The
image defaults to UID/GID 1000; Compose accepts `LOCAL_UID` and `LOCAL_GID` for
other users. Retain these settings in your shell or a local Compose `.env` file
for subsequent commands. Never commit `.env`, credentials or live configuration.
The image does not require root, privileged mode or access to the Docker socket.

`init` creates missing files only. It does not overwrite configuration, devices,
sender assignments or tokens. It creates no admin credential. Its initial
configuration has no radio adapter, disables TX, enables SQLite and requires
API authentication. The MQTT broker is not bundled.

## 2. Configure MQTT and authentication

```sh
nano config/config.json
docker compose run --rm --no-deps -it --entrypoint enocean-mqtt-auth \
  enocean-mqtt init --name admin
```

Set `mqtt.host` to a broker reachable from the container. `localhost` would mean
the container itself, not the host. For a broker on another machine, use its LAN
address. Use a distinct `mqtt.client_id` for each instance. If credentials are
needed, place the MQTT password in `config/secrets/` and set `password_file` to
the corresponding container path, for example `config/secrets/mqtt-password`.
Store the displayed admin token in your password manager; it is also your Web UI
password. Do not disable authentication to simplify setup.

The [configuration and authentication guide](README.md) applies unchanged. Paths
in `config.json` refer to the container, relative to `/app`, not the host. Keep
`config/config.json` as the container configuration path so Web UI configuration
management and liveness checks refer to the same file.

## 3. Start without hardware

```sh
docker compose up -d
docker compose logs --tail=100 -f
```

The default port mapping is deliberately restricted to host loopback:
`http://127.0.0.1:8001/`. For access from another machine, set `WEB_BIND_ADDRESS`
to the host's LAN address before starting, or configure a protected reverse proxy.
Keep authentication enabled, apply firewall restrictions and use HTTPS on
untrusted networks. Do not expose the gateway directly to the Internet.

The health check verifies configuration readability and, when enabled, the Web
API TCP listener. It does not prove MQTT connectivity, radio reception, actuator
state or successful pairing. An unhealthy status alone does not restart a Docker
container; the configured restart policy applies when the process exits.

## 4. Optional USB300 on a Linux host

Stop any existing native service using this adapter. Never let the service and
container run concurrently against the same stick or MQTT client ID. The runtime
lock inside a container does not lock out a separate host installation.

```sh
ls -l /dev/serial/by-id/
export ENOCEAN_USB_DEVICE=/dev/serial/by-id/REPLACE_WITH_YOUR_ADAPTER
export ENOCEAN_USB_GID="$(stat -Lc '%g' "$ENOCEAN_USB_DEVICE")"
```

Add this section in `config/config.json`, retaining TX disabled until you have
reviewed your sender allocation and transmission requirements:

```json
"enocean": {
  "default_interface": "usb300",
  "tx_enabled": false,
  "interfaces": [
    {
      "interface_id": "usb300",
      "enabled": true,
      "type": "serial_esp3",
      "device": "/dev/enocean",
      "baudrate": 57600
    }
  ]
}
```

```sh
docker compose -f compose.yaml -f compose.usb.yaml up -d
```

Use both Compose files for subsequent USB deployment commands. The adapter is
mapped to `/dev/enocean` in the container and its numeric device group is added
to the process. No whole `/dev` mount or privileged container is necessary.
The by-id path identifies the intended host adapter, but device passthrough is
resolved when the container starts. After unplug/replug or device renumbering,
recheck the path/group and recreate the container with `up -d --force-recreate`.
USB passthrough on Docker Desktop is outside this Linux deployment guide.

## Data, updates and recovery

| Host directory | Container directory | Contents |
|---|---|---|
| `config/` | `/app/config/` | Runtime configuration, devices, gateways, foreign devices, sender allocations and secrets |
| `data/` | `/app/data/` | SQLite database, including journal/WAL files |
| `export/` | `/app/export/` | CSV imports/exports configured by container initialization |

Mount directories, not individual JSON or SQLite files: atomic file replacement
and SQLite sidecars need a writable parent directory. Keep configuration and
secrets readable only by the deployment user. The application files and bundled
profiles remain in the read-only image and are updated with it. An optional custom
profile can be mounted as an individual read-only file under `/app/eep/registry/`;
do not mask the whole directory unless you intentionally maintain the entire
profile set yourself.

For an update, stop the container, back up all three deployment directories, set
`ENOCEAN_MQTT_TAG` to the chosen released version, then pull and recreate it:

```sh
docker compose stop
# Back up config/, data/ and export/ while stopped.
export ENOCEAN_MQTT_TAG=0.10.0
docker compose pull
docker compose up -d
```

Use version tags for controlled upgrades; `latest` follows the newest published
image. Check the changelog before upgrading. Existing configuration is never
automatically replaced by `init`; review new defaults explicitly. Shipped
`device-controller-mappings.json` is seeded on initialization and then preserved
like the other configuration files. Back it up and compare new shipped defaults
when controller defaults change. Per-device `tx_profile` remains the customization
mechanism. An image rollback may require restoring its matching data backup.

`docker compose stop` sends SIGTERM and allows up to 30 seconds for Web API,
serial interfaces, SQLite and MQTT to close. Application-requested restart
replaces the process in the same container. Container logs are available through
Docker, with bounded log rotation in the supplied Compose file.

For admin recovery, stop the service and use the same bind mounts and user:

```sh
docker compose stop
docker compose run --rm --no-deps -it --entrypoint enocean-mqtt-auth \
  enocean-mqtt recover --name admin
docker compose up -d
```

For migration from a native installation, stop it first and copy its complete
configuration and sender-ID registry, not just the device list. Copy SQLite while
stopped and translate absolute paths into container paths. Do not operate two
clones with the same sender allocation independently. Keep the previous service
disabled until the migration has been accepted.

## Build and validation

The Dockerfile builds from the source tree. To build a local image instead of
pulling a published one:

```sh
docker build -t enocean-mqtt:local .
```

Only allowlisted runtime files enter the build context. The build installs Python
dependencies, while radio access and user data are configured at deployment.
The image pipeline builds and tests AMD64 and ARM64 independently before publishing
the tested images as one multi-platform tag. Its acceptance test covers API
authentication, profile loading, read-only execution, SIGTERM and data persistence
across container replacement. This does not replace USB300 RX/TX hardware tests.
See [Known Limitations](../KNOWN_LIMITATIONS.md) for protocol support boundaries.
