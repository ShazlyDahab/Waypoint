// Lifecycle tests: these are the ones that catch a splash leaking a rAF loop
// behind the app, or ignoring reduced-motion.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import SplashScreen from "./SplashScreen";

function mockMatchMedia(reduced: boolean) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: (query: string) => ({
      matches: reduced && query.includes("reduced-motion"),
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  });
}

beforeEach(() => {
  mockMatchMedia(false);
  // jsdom has no canvas backend; the component must not crash without one.
  HTMLCanvasElement.prototype.getContext = vi.fn(() => null) as never;
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("rAF lifecycle", () => {
  it("cancels its animation frame on unmount — no loop left running behind the app", () => {
    const rafIds: number[] = [];
    let next = 1;
    const raf = vi.spyOn(window, "requestAnimationFrame").mockImplementation(() => {
      const id = next++;
      rafIds.push(id);
      return id;
    });
    const cancel = vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => {});
    // A real 2D context so the physics effect actually starts its loop.
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ({
      setTransform: vi.fn(), clearRect: vi.fn(), beginPath: vi.fn(),
      arc: vi.fn(), fill: vi.fn(), globalAlpha: 1, fillStyle: "",
    })) as never;

    const { unmount } = render(<SplashScreen />);
    expect(raf).toHaveBeenCalled();

    unmount();
    expect(cancel).toHaveBeenCalled();
    // The id cancelled must be one this component actually requested.
    const cancelled = cancel.mock.calls.map((c) => c[0]);
    expect(rafIds).toEqual(expect.arrayContaining(cancelled));
  });

  it("removes its window listeners on unmount", () => {
    const winSpy = vi.spyOn(window, "removeEventListener");
    const docSpy = vi.spyOn(document, "removeEventListener");

    const { unmount } = render(<SplashScreen />);
    unmount();

    const removed = [
      ...winSpy.mock.calls.map((c) => c[0]),
      ...docSpy.mock.calls.map((c) => c[0]),
    ];
    expect(removed).toContain("keydown");
    expect(removed).toContain("pointerdown");
  });
});

describe("reduced motion", () => {
  it("skips physics entirely — no canvas, no rAF loop", () => {
    mockMatchMedia(true);
    const raf = vi.spyOn(window, "requestAnimationFrame");
    const { container } = render(<SplashScreen />);

    expect(container.querySelector("canvas")).toBeNull();
    expect(raf).not.toHaveBeenCalled();
  });

  it("still reaches the finished lockup and hands off", async () => {
    mockMatchMedia(true);
    const onFinish = vi.fn();
    render(<SplashScreen onFinish={onFinish} />);
    await waitFor(() => expect(onFinish).toHaveBeenCalled(), { timeout: 2000 });
  });
});

describe("bootstrap", () => {
  it("surfaces a failure instead of spinning forever", async () => {
    const bootstrap = () => Promise.reject(new Error("the server answered 500"));
    render(<SplashScreen bootstrap={bootstrap} />);
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain("the server answered 500")
    );
  });

  it("announces loading state to assistive tech", () => {
    render(<SplashScreen />);
    expect(screen.getByRole("status").textContent).toBe("Loading Waypoint");
  });

  it("hides the decorative canvas from assistive tech", () => {
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ({
      setTransform: vi.fn(), clearRect: vi.fn(), beginPath: vi.fn(),
      arc: vi.fn(), fill: vi.fn(), globalAlpha: 1, fillStyle: "",
    })) as never;
    const { container } = render(<SplashScreen />);
    expect(container.querySelector("canvas")?.getAttribute("aria-hidden")).toBe("true");
  });
});
