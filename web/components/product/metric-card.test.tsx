import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MetricCard } from "@/components/product/metric-card";

describe("MetricCard", () => {
  it("renders a labelled metric and its context", () => {
    render(<MetricCard label="Retorno total" value="+36,2%" delta="vs. IBOV" tone="positive" />);
    expect(screen.getByText("Retorno total")).toBeInTheDocument();
    expect(screen.getByText("+36,2%")).toBeInTheDocument();
    expect(screen.getByText("vs. IBOV")).toBeInTheDocument();
  });
});
