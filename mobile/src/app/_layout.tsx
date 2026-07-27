import {
  Fraunces_600SemiBold,
  Fraunces_700Bold,
} from "@expo-google-fonts/fraunces";
import {
  IBMPlexMono_400Regular,
  IBMPlexMono_500Medium,
} from "@expo-google-fonts/ibm-plex-mono";
import {
  SourceSans3_400Regular,
  SourceSans3_600SemiBold,
} from "@expo-google-fonts/source-sans-3";
import { useFonts } from "expo-font";
import { Stack } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { colors, fonts } from "../lib/theme";

SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  const [loaded, error] = useFonts({
    Fraunces_600SemiBold,
    Fraunces_700Bold,
    IBMPlexMono_400Regular,
    IBMPlexMono_500Medium,
    SourceSans3_400Regular,
    SourceSans3_600SemiBold,
  });

  useEffect(() => {
    if (loaded || error) SplashScreen.hideAsync();
  }, [loaded, error]);

  if (!loaded && !error) return null;

  return (
    <>
      <StatusBar style="dark" />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: colors.paper },
          headerTintColor: colors.ink,
          headerTitleStyle: { fontFamily: fonts.displayBold, fontSize: 20 },
          headerShadowVisible: false,
          contentStyle: { backgroundColor: colors.paper },
        }}
      >
        <Stack.Screen name="index" options={{ title: "Attest" }} />
        <Stack.Screen name="run/[id]" options={{ title: "Verification run" }} />
        <Stack.Screen name="calibration" options={{ title: "The guarantee" }} />
      </Stack>
    </>
  );
}
