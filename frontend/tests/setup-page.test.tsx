import React from "react";
import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";

import SetupPage from "../src/app/setup/page";

describe("SetupPage", () => {
  it("renders the first-run setup shell", () => {
    const html = renderToString(<SetupPage />);
    expect(html).toContain("First-Run Setup");
    expect(html).toContain("Primary Admin");
    expect(html).toContain("Loading setup status");
  });
});
