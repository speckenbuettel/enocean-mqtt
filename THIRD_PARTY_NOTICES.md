# Third-party notices

The project's own code is licensed under the [MIT License](LICENSE).
That license does not relicense third-party specifications, manuals, libraries
or other protected material. See [Credits and Sources](CREDITS.md) for dependency
and technical-reference links.

## EnOcean Equipment Profiles

The project's EnOcean runtime profiles are independently prepared JSON
implementations of technical parameters described by the EnOcean Alliance.
Source documents and versions are recorded in individual profile metadata.
This notice applies to selected EnOcean profiles distributed in `eep/registry/`;
it is not a declaration that every available profile is supported or tested.

Technical sources include the EnOcean Equipment Profiles definitions (XML 2.6.8)
and profile-specific IP representations, where identified in profile metadata.
The [EnOcean Equipment Profiles Specification, version 3.1](https://www.enocean-alliance.org/eep/)
identifies the EnOcean Alliance as the rights holder and permits free use for
non-commercial purposes, including evaluation and development of non-commercial
tools and documentation. The maintainer uses these sources for non-commercial
development of `enocean-mqtt`.

The specification also states conditions for using its content in development of
products or services for sale, involving Alliance membership and/or appropriate
joint intellectual-property ownership. Consult the source's actual conditions
before such use. The MIT license for this project's own code does not override
those conditions or grant rights to third-party intellectual property.

Original Alliance PDFs, XML definitions and IP source documents are not included
in the public distribution. Profile metadata and this notice preserve provenance;
they do not represent permission from, certification by or endorsement by the
EnOcean Alliance. This document does not assign a new non-commercial license to
the project's own code or assert that all technical facts are copyrighted.

## Eltako manufacturer-specific profiles

The independently prepared runtime profiles `eep/registry/eltako-ftkb.json`,
`eep/registry/eltako-fhmb.json` and `eep/registry/eltako-fud70s.json`, when included
in a release, use technical
information from [Eltako](https://www.eltako.com/) device documentation.
Consult their source metadata for the applicable document and version.

Manufacturer manuals are technical references, not MIT-licensed project
documentation. Their public availability or inclusion with purchased devices is
not represented here as a blanket redistribution license. Original manuals,
illustrations and substantial copied explanatory passages are not included in
the public distribution. Profile descriptions should be independently worded;
technical identifiers and parameter definitions retain their source attribution.
No manufacturer endorsement or certification is claimed.

## Dependencies and other distributions

Third-party dependencies retain their respective licenses. The dependency links
in [CREDITS.md](CREDITS.md) are acknowledgments, not substitutes for the license
texts and notices required when those dependencies are redistributed.

This notice describes the source distribution. A future bundled application or
container must retain the notices required by the exact dependencies and assets
it includes. It must not treat this document as a complete bundled-software
license inventory.
