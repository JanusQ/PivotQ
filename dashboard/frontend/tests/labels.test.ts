import { describe, expect, it } from "vitest";
import { forecastShare, targetLabel } from "../src/api/labels";

describe("forecast presentation", () => {
  it("keeps small positive contributions distinguishable from zero", () => {
    expect(forecastShare(0, 100)).toBe("占预计总耗时 0%");
    expect(forecastShare(0.001, 100)).toBe("占比 <1%");
    expect(forecastShare(0.99, 100)).toBe("占比 <1%");
    expect(forecastShare(1, 100)).toBe("占预计总耗时 1%");
    expect(forecastShare(94, 100)).toBe("占预计总耗时 94%");
    expect(forecastShare(1, 0)).toBe("占比未提供");
    expect(forecastShare(NaN, 100)).toBe("占比未提供");
  });
  it("does not relabel arbitrary registered hardware as a virtual target", () => {
    expect(targetLabel({ id: "physical", title: "Lab QPU" })).toBe("Lab QPU");
    expect(targetLabel({ id: "fake-sc-36", title: "Fake SC-36" })).toContain("虚拟");
  });
});
