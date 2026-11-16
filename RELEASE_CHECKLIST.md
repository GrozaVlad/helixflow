# Before public release

- [ ] Review this new repository for secrets/private information; no old Git history was copied.
- [ ] Complete Apache-2.0 license text and third-party notices (including vendored Mol*).
- [ ] Review scientific-input/MSA redistribution terms and publish the frozen workload archive.
- [ ] Curate and archive full per-attempt evidence; current public candidate contains selected records.
- [ ] Verify anonymous access to the immutable Docker study image.
- [ ] Archive a browser example with expected outputs and a genuine viewer screenshot.
- [ ] Complete independent author review and declarations in the separately maintained manuscript.
- [ ] Select and tag the evaluated release, publish an archival DOI, and add citation metadata.
- [ ] Check public installation/reproduction links from a clean environment.

No commit, push, visibility change, deployment or release publication was performed
by the migration. The automated cloud deployment workflow was deliberately not
enabled in this repository; CI checks were retained. AWS remains experimental.

The original `bolts_paper` working tree and all results were preserved. Import hashes
record the copied files before destination-specific README/generator edits. The
Git-ignored staged workload archive must be backed up/published separately; cloning
this repository alone will not obtain those MSAs.
