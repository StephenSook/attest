# Attest Pocket

The patient-side companion app for [Attest](../README.md): iOS and Android,
Expo SDK 57, TypeScript.

Read-only against the same production API as the web console. It shows the
runs ledger, a run's verdict stamp with its evidence spans and transcript,
the receiving-end call audio synced to the transcript, a shareable signed
attestation certificate, and the measured coverage guarantee. Nothing is
baked into the app; every number is served.

## Run it

```bash
npm install
npx expo start --ios      # or --android

npx tsc --noEmit                                     # typecheck the app
node --experimental-strip-types --test "src/**/*.test.ts"   # unit tests
```

Tests run on Node's built-in runner with no test framework installed. They are
excluded from `tsc` because satisfying their `node:` imports would mean pulling
`@types/node` into a React Native app, where it shadows the platform's own
globals.

The API base URL comes from `expo.extra.apiBase` in `app.json` and defaults
to the deployed backend, so the app works on a fresh clone with no setup.

## Install the built app

- Android: the APK on the [latest release](https://github.com/StephenSook/attest/releases/latest)
- iOS: [TestFlight](https://testflight.apple.com/join/XZDXt7jw), build 1.0.0 (3), approved by Apple Beta App Review and open to anyone

## Layout

```
src/app/          expo-router screens (ledger, run detail, calibration)
src/components/   VerdictStamp and shared pieces
src/lib/          api client and the evidence-ledger design tokens
```
