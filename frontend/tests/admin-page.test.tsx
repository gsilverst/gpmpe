import React from "react";
import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";

import AdminPage from "../src/app/admin/page";

describe("AdminPage", () => {
  it("renders user invite and repository sections", () => {
    const html = renderToString(<AdminPage />);
    expect(html).toContain("Admin Settings");
    expect(html).toContain("Users");
    expect(html).toContain("Invite user");
    expect(html).toContain("Business Data Repository");
  });
});
