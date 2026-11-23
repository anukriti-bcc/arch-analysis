import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import RealAdrChecks from "./RealAdrChecks.jsx";
import { mockApi } from "../test/mockApi.js";
import checks from "../__fixtures__/real_adr_checks.json";

afterEach(() => vi.unstubAllGlobals());
const route = (body) => [["GET", /\/experiments\/real-adr-checks$/, body]];

describe("RealAdrChecks", () => {
  it("shows the false-permission headline with its band and interval", async () => {
    mockApi(route(checks));
    render(<RealAdrChecks />);
    const fp = within(await screen.findByTestId("false-permission"));
    expect(fp.getByTestId("fp-dangerous")).toHaveTextContent("0 / 44");
    expect(fp.getByText(/band LOW/)).toBeInTheDocument();
    expect(fp.getByText(/0\.0% to 8\.0%/)).toBeInTheDocument();
    expect(fp.getByText(/not a claim that it is zero/)).toBeInTheDocument();
  });

  it("states what the probe does not show, and flags the routing artefact when all cases went structural", async () => {
    mockApi(route(checks));
    render(<RealAdrChecks />);
    expect(await screen.findByText(/one failure direction/)).toBeInTheDocument();
    expect(screen.getByTestId("fp-routing-note")).toHaveTextContent("by construction");
  });

  it("omits the routing note when some cases did reach the model", async () => {
    const fp = { ...checks.false_permission, routes: { structural: 40, code_reader: 0, model: 4 } };
    mockApi(route({ ...checks, false_permission: fp }));
    render(<RealAdrChecks />);
    await screen.findByTestId("false-permission");
    expect(screen.queryByTestId("fp-routing-note")).not.toBeInTheDocument();
  });

  it("reports the case study against the always-violation baseline and the hidden violation", async () => {
    mockApi(route(checks));
    render(<RealAdrChecks />);
    const cs = within(await screen.findByTestId("case-study"));
    expect(cs.getByText(/correct on 5 of 7/)).toBeInTheDocument();
    expect(cs.getByText(/no evidence that the model beats that baseline/)).toBeInTheDocument();
    expect(cs.getByTestId("cs-hidden")).toHaveTextContent("1 real violation was called justified");
    expect(cs.getAllByTestId("cs-row")).toHaveLength(7);
    expect(cs.getByText(/demonstration, not a rate/)).toBeInTheDocument();
  });

  it("shows only the part whose results exist", async () => {
    mockApi(route({ ...checks, case_study: null }));
    render(<RealAdrChecks />);
    await screen.findByTestId("false-permission");
    expect(screen.queryByTestId("case-study")).not.toBeInTheDocument();
  });

  it("renders nothing when there are no results or the request fails", async () => {
    mockApi(route({ false_permission: null, case_study: null }));
    const { container, unmount } = render(<RealAdrChecks />);
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
    unmount();
    mockApi([["GET", /real-adr-checks/, { __status: 500, detail: "boom" }]]);
    const again = render(<RealAdrChecks />);
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    expect(again.container).toBeEmptyDOMElement();
  });
});
