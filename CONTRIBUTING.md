# Contributing

Thank you for helping improve `enocean-mqtt`. Start with the [User Guide](userguide/README.md)
and [Known Limitations](KNOWN_LIMITATIONS.md) to check the current scope.

## Issues and device requests

Use the [public issue tracker](https://github.com/speckenbuettel/enocean-mqtt/issues)
for reproducible bugs, documentation suggestions and device/EEP requests.

For a bug report, include the project version, operating system, Python version,
interface model, relevant EEP/device model, reproduction steps, expected behavior
and actual behavior. Include only the smallest sanitized configuration and log
excerpt needed to reproduce the problem.

For a device request, link to official documentation and describe which operations
were tested: decoding, transmission, Teach-In or confirmed device feedback. A
compiled profile is not evidence of a successful hardware test. If sharing
telegram samples, explain which values and fields are relevant.

Never post API tokens, passwords, private keys, full live configurations, databases
or unfiltered captures. Remove or consistently pseudonymize installation-specific
identifiers, addresses and device names. Do not upload third-party manuals unless
you have permission to redistribute them; prefer links to the publisher.

Do not post credentials or exploit details for a suspected security vulnerability
in a public issue. Arrange a private reporting channel with the maintainer first.

## Pull requests

Small, focused pull requests against the public repository's `main` branch are
welcome. Discuss changes to protocol behavior, API/MQTT contracts or profile
semantics before a large implementation.

1. Describe the problem and the intended behavior.
2. Keep unrelated refactoring and generated-file churn out of the change.
3. Update affected user documentation and provide reproducible verification steps.
4. Report which checks actually ran, their results and any untested hardware paths.
5. Identify any reused code or data, its source and applicable license/notices.

The public repository contains selected runtime releases. Development tooling,
compiler source inputs and the internal test suite are maintained separately and
may not be available in a public checkout. Maintainers reconcile accepted public
changes with the development source and run the relevant internal checks before
the next release. Contributors do not need access to private files to report a
bug or propose a runtime fix.

## Local verification

Follow the User Guide for installation and a smoke test. Use an isolated test
configuration and MQTT broker/topic namespace. Prefer hardware-free replay for
decoder changes; it does not validate live transmission or pairing. Never test
actuator commands on an occupied or production installation without the owner's
explicit approval and appropriate precautions.

If the checkout contains the development test suite, add regression coverage for
changed behavior and use the checks defined by that checkout. If tests or hardware
are unavailable, say so rather than claiming validation.

## Profiles, generated data and versions

Do not bulk-regenerate or hand-edit generated profile/catalogue outputs merely to
make a diff look consistent. Describe the source correction and expected output
so maintainers can reproduce it with the relevant source inputs. Treat semantic
changes as behavior changes, including units, ranges, enum values and RX/TX roles.

For an intentionally source-grounded new or revised profile, use the
[profile-authoring workflow](userguide/profile-authoring.md) and retain its source
correspondence, human decisions and verification record. Direct authoring does
not waive review or authorize bulk replacement of existing profiles.

[VERSION](VERSION) is the canonical project version. Do not introduce an
independent version string or change release numbering as part of an unrelated
fix; see [Versioning](docs/project-versioning.md).

The project's own code uses the [MIT License](LICENSE). Submit only material you
are entitled to contribute and preserve third-party notices. See [Credits and
Sources](CREDITS.md) for dependency and reference acknowledgments.
