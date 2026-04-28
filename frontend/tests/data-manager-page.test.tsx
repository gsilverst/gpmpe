import React from "react";
import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";

import DataManagerPage from "../src/app/data-manager/page";

describe("DataManagerPage", () => {
  it("renders the step 4a heading", () => {
    const html = renderToString(<DataManagerPage />);
    expect(html).toContain("Step 4a Data Manager");
    expect(html).toContain("Select a business");
    expect(html).toContain("Campaign Detail");
    expect(html).toContain("No campaign selected.");
  });
});
