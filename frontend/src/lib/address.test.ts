import { describe, expect, it } from "vitest";

import { isHomeAddress, isLoopbackAddress } from "./address";

describe("loopback addresses", () => {
  it.each([
    "http://localhost:7867",
    "http://127.0.0.1:4173",
    "http://[::1]:7867",
    "http://app.localhost",
  ])("%s is only for this computer", (address) => {
    expect(isLoopbackAddress(address)).toBe(true);
  });

  it.each([
    "http://sunroom.local:7867",
    "https://calendar.example.com",
    "http://192.168.1.20:7867",
    "not a url",
  ])("%s is not", (address) => {
    expect(isLoopbackAddress(address)).toBe(false);
  });
});

describe("home addresses (a photo library's home-network switch starts ticked, ADR 0036)", () => {
  it.each([
    "http://192.168.1.30:2283",
    "192.168.1.30:2283",
    "http://10.0.0.5",
    "http://172.16.4.2:2283",
    "http://172.31.255.1",
    "http://169.254.10.1",
    "http://localhost:2283",
    "http://[fd12:3456::1]:2283",
    "http://immich:2283",
    "http://nas.local:2283",
    "http://photos.lan",
    "http://immich.home",
    "https://photos.internal",
  ])("%s is at home", (address) => {
    expect(isHomeAddress(address)).toBe(true);
  });

  it.each([
    "https://photos.example.com",
    "http://172.32.0.1",
    "http://8.8.8.8",
    "http://immich.test",
    "",
    "http://",
  ])("%s isn't", (address) => {
    expect(isHomeAddress(address)).toBe(false);
  });
});
