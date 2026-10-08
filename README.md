# Cloudified SideStore source

Add this URL in SideStore's Sources screen:

https://raw.githubusercontent.com/tinyredphoenix/Cloudified-Source/main/source.json

This public source lists successful **unsigned CI builds** of [Cloudified](https://github.com/tinyredphoenix/Cloudified), a personal original-photo/video uploader. SideStore signs the selected IPA with your own certificate. A successful build is not evidence that Google Photos, Telegram, background execution, metadata preservation, or reinstall recovery work on an iPhone.

- [Source JSON](source.json): app listing and versioned downloads, newest build first.
- [Build results](builds.json): successful, failed, cancelled, and timed-out manual build runs.
- [Releases](https://github.com/tinyredphoenix/Cloudified-Source/releases): permanent IPA and SHA-256 assets for successful runs.

The Cloudified build workflow remains manual. Its completed-run publisher stages verified IPA bytes in the application repository, then sends a small result manifest here through a repository-specific write key. This repository downloads and checks those bytes before publishing its own release and source entry. No signing material or personal media belongs in either repository.
