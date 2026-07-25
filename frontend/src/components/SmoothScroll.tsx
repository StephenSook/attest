import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import Lenis from "lenis";
import { useEffect, type ReactNode } from "react";

gsap.registerPlugin(ScrollTrigger);

let activeLenis: Lenis | null = null;
export const getLenis = () => activeLenis;

/* Global smooth scrolling via Lenis, driven by the GSAP ticker so
   ScrollTrigger and Lenis share one clock. Disabled entirely under
   prefers-reduced-motion: native scrolling is the accessible baseline. */
export default function SmoothScroll({ children }: { children: ReactNode }) {
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      return;
    }
    const lenis = new Lenis({ lerp: 0.12, wheelMultiplier: 1 });
    activeLenis = lenis;
    lenis.on("scroll", ScrollTrigger.update);
    const tick = (time: number) => lenis.raf(time * 1000);
    gsap.ticker.add(tick);
    gsap.ticker.lagSmoothing(0);
    return () => {
      gsap.ticker.remove(tick);
      lenis.destroy();
      activeLenis = null;
    };
  }, []);
  return <>{children}</>;
}
