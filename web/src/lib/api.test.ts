import { describe, expect, test } from "vitest";
import { accessCode, socketUrl, withCode } from "./api";

describe("access code", () => {
  test("is taken from the link and remembered", () => {
    localStorage.clear();
    expect(accessCode("?code=burrell26", localStorage)).toBe("burrell26");
    expect(accessCode("", localStorage)).toBe("burrell26");
  });

  test("still works when the browser blocks storage", () => {
    const blocked = {
      getItem: () => { throw new Error("blocked"); },
      setItem: () => { throw new Error("blocked"); },
    } as unknown as Storage;
    expect(accessCode("?code=abc", blocked)).toBe("abc");
    expect(accessCode("", blocked)).toBe("");
  });

  test("is added to paths", () => {
    expect(withCode("/api/pack", "abc")).toBe("/api/pack?code=abc");
    expect(withCode("/api/x?y=1", "a b")).toBe("/api/x?y=1&code=a%20b");
    expect(withCode("/api/pack", "")).toBe("/api/pack");
  });

  test("goes on the socket URL with the right scheme", () => {
    const secure = { protocol: "https:", host: "guide.example" } as Location;
    expect(socketUrl("abc", secure)).toBe("wss://guide.example/ws/session?code=abc");
    const local = { protocol: "http:", host: "localhost:5173" } as Location;
    expect(socketUrl("", local)).toBe("ws://localhost:5173/ws/session");
  });
});
