# Credits and Sources

`enocean-mqtt` is maintained by Falk G. Schulte (fgs-IT | smart.home.singapore).
Thank you to the maintainers of the open-source libraries and technical
specifications that make this project possible, and to contributors who provide
reproducible bug reports, documentation improvements and hardware test results.

## Open-source dependencies

The direct runtime dependencies are declared in [pyproject.toml](pyproject.toml).
The following links identify their upstream projects and license information;
the license files supplied with the installed versions remain authoritative.

| Project | Use in enocean-mqtt | Upstream license information |
|---|---|---|
| [FastAPI](https://github.com/fastapi/fastapi) | HTTP API and web application framework | [MIT](https://github.com/fastapi/fastapi/blob/master/LICENSE) |
| [Jinja](https://github.com/pallets/jinja) | HTML templates | [BSD-3-Clause](https://github.com/pallets/jinja/blob/main/LICENSE.txt) |
| [Uvicorn](https://github.com/Kludex/uvicorn) | ASGI application server | [BSD-3-Clause](https://github.com/Kludex/uvicorn/blob/main/LICENSE.md) |
| [Eclipse Paho MQTT Python](https://github.com/eclipse-paho/paho.mqtt.python) | MQTT client | [EPL-2.0 / EDL-1.0 dual license](https://github.com/eclipse-paho/paho.mqtt.python/blob/master/LICENSE.txt) |
| [pySerial](https://github.com/pyserial/pyserial) | Serial communication with EnOcean interfaces | [BSD-3-Clause](https://github.com/pyserial/pyserial/blob/master/LICENSE.txt) |
| [Pydantic](https://github.com/pydantic/pydantic) | Data models and validation | [MIT](https://github.com/pydantic/pydantic/blob/main/LICENSE) |
| [psutil](https://github.com/giampaolo/psutil) | System and process metrics | [BSD-3-Clause](https://github.com/giampaolo/psutil/blob/master/LICENSE) |
| [tzdata](https://github.com/python/tzdata) | Time-zone data for Python | [Apache-2.0 package license](https://github.com/python/tzdata/blob/master/LICENSE) |

FastAPI also provides the interactive API documentation using
[Swagger UI](https://github.com/swagger-api/swagger-ui)
([Apache-2.0](https://github.com/swagger-api/swagger-ui/blob/master/LICENSE)) and
[ReDoc](https://github.com/Redocly/redoc)
([MIT](https://github.com/Redocly/redoc/blob/main/LICENSE)). The application uses
FastAPI's default documentation pages; their browser assets are loaded from
external URLs configured by FastAPI, rather than vendored in this repository.

The default ReDoc page also requests Montserrat and Roboto through Google Fonts;
the default API documentation pages use a FastAPI-hosted favicon. These external
assets are separate from the application's own artwork and are not bundled here.
API documentation therefore requires access to external services, not only the
gateway. Reassess their versions, terms and notices if they are bundled later.

This is an acknowledgment of direct dependencies and documentation components,
not a complete inventory of installed software. Transitive dependencies have
their own licenses. Dependency versions and any bundled assets must be reviewed
for each distribution format.

## Protocol and device references

- [EnOcean Alliance technical specifications](https://www.enocean-alliance.org/specifications/),
  including EnOcean Equipment Profiles (EEP) and EnOcean over IP material, provide
  protocol and parameter context for profile interpretation and semantic review.
- [EnOcean](https://www.enocean.com/) provides the EnOcean Serial Protocol 3 (ESP3)
  and interface documentation used as technical references.
- [Eltako](https://www.eltako.com/) device documentation is a reference for the
  proprietary FTKB, FHMB-rw and FUD70S profiles. Profile metadata records the relevant
  source document/version where available.

These are technical references, not claims that their authors contributed code,
endorsed this project or certified its hardware support. Referenced specifications
and manufacturer manuals are not included in the public source distribution.
Referencing a document does not grant permission to redistribute it or material
derived from it; selected profile data require a separate provenance review.

## Project artwork

The repository's project logo, icon and favicon were created specifically for
`enocean-mqtt`. The maintainer confirmed on 2026-10-09 that they contain no
third-party image components or logos. They are not EnOcean Alliance certification
marks and do not imply vendor endorsement.

## License boundaries

The project's own code is released under the [MIT License](LICENSE). This does not
relicense third-party libraries, specifications, data or other third-party
material. Their respective licenses and notices continue to apply.

See [Third-party Notices](THIRD_PARTY_NOTICES.md) for the source and usage
boundaries of EnOcean and manufacturer-specific runtime profiles.

This credits page does not replace required copyright statements, license texts
or notices when third-party material is redistributed. Such material must retain
the applicable notices in the distributed artifact.
