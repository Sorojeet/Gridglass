# Gridglass for Android (Google Play)

A Trusted Web Activity: a small Android app that opens https://gridglass.in full-screen in Chrome.
It has no code of its own beyond the launcher, so every website deploy updates the app too.
Sharing a file to Gridglass and opening CSV/Excel files with it work as in the installed web app.

- Package name: `com.gridglass.app` (fixed forever once uploaded to Play).
- Generated with [Bubblewrap](https://github.com/GoogleChromeLabs/bubblewrap) from `twa-manifest.json`,
  then edited: Android share filters list MIME types only, and signing and the version code come
  from the environment (`app/build.gradle`).

## Building

GitHub Actions -> **Android app** -> **Run workflow**. It builds a signed `.aab` and attaches it to the run
(download it from the run's page). Each run's number is the version code, so every build can be uploaded.

It needs two repository secrets (Settings -> Secrets and variables -> Actions):

| Secret | What |
| --- | --- |
| `ANDROID_KEYSTORE_BASE64` | the upload keystore (`.jks`), base64-encoded |
| `ANDROID_KEYSTORE_PASSWORD` | its password (the key uses the same password; alias `upload`) |

Keep a copy of the keystore and password somewhere safe. With Play App Signing (the default) Google
holds the real signing key; if the upload key is lost, ask Play Console support to reset it.

To make your own key instead:
`keytool -genkeypair -keystore upload-key.jks -storetype PKCS12 -alias upload -keyalg RSA -keysize 4096 -validity 10000`
then `base64 -w0 upload-key.jks`.

## Full-screen (no URL bar): Digital Asset Links

Android only hides the URL bar if https://gridglass.in/.well-known/assetlinks.json lists the app's
signing certificate. Set `ANDROID_CERT_SHA256` on Render to a comma-separated list of:

1. the **app signing key** SHA-256 from Play Console -> Test and release -> App integrity
   (appears after the first upload), and
2. the **upload key** SHA-256 (printed by the workflow), so builds installed directly also work.

## Releasing a new version of the app

Only needed when something in `android/` changes (name, icon, colours, share types); website changes
reach the app on their own. Edit `twa-manifest.json` and the generated files to match, bump
`versionName` in `app/build.gradle`, run the workflow and upload the new `.aab`.
