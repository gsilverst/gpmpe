import React from "react";
import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";

import HomePage from "../src/app/page";

describe("HomePage", () => {
  it("renders the app shell heading", () => {
    const html = renderToString(<HomePage />);
    expect(html).toContain("GPMPE");
    expect(html).toContain("Backend Health Check");
  });
});
