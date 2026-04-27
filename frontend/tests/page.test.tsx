import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";

import HomePage from "../src/app/page";

describe("HomePage", () => {
  it("renders the app shell heading", () => {
    const html = renderToString(<HomePage />);
    expect(html).toContain("GPMPG");
    expect(html).toContain("Backend Health Check");
  });
});
