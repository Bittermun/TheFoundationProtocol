# Separately installed IIAB pilot

This is an optional operator add-on, not an upstream IIAB integration or a verified IIAB release. Keep the existing IIAB catalog/content manager untouched. Use a dedicated adapter catalog and separately configured Kiwix reader instance; add a local menu link only after a successful pilot.

1. Install `tfp[library]` into a dedicated virtual environment at `/opt/tfp-library` and Kiwix/openZIM tools using the host's supported method.
2. Provision the service account `tfp-library`, configuration, pinned publisher public key, and private transport key. Configure actual tool/base paths; the sample paths are not discovery logic.
3. Give the updater ownership of its catalog/state/archive directories, and the reader account catalog-read and directory-traversal access. The updater must be able to preserve the catalog's owner/group when replacing it. Keep private-state mode 0700. Archives contain public content and are 0644 in a 0755 directory.
4. Create the dedicated catalog with `kiwix-manage library.xml add BASE.zim`. Run a Kiwix instance with `--library --monitorLibrary`, the dedicated catalog and a separate available port; configure its LAN exposure explicitly.
5. Receive/copy a signed package into `incoming`; activate manually with the CLI or the provided oneshot systemd unit. No timer, background radio broadcast, content-manager hook or service restart is installed automatically.
6. Verify an old page, the new page, restart recovery, low-end-phone browsing and coexistence with the original IIAB library before offering support for that particular IIAB release.

Uninstall: disable/remove the optional unit, remove the optional menu link/reader instance, and retain archives/catalog/state until the operator has copied anything needed. No automatic data deletion is provided.

See `docs/offline_library_pilot.md` for commands, trust policy and recovery behavior.
