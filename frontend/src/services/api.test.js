import { ApiError, api } from "./api.js";

function mockFetch(status, body) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText: "error",
    json: async () => body,
  });
}

describe("api", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("GET returns parsed JSON", async () => {
    const fetchMock = mockFetch(200, { pair: "EURUSD", rate: 1.0862 });
    vi.stubGlobal("fetch", fetchMock);

    const data = await api.get("/market-data/rates?pair=EURUSD");

    expect(data).toEqual({ pair: "EURUSD", rate: 1.0862 });
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toContain("/market-data/rates?pair=EURUSD");
    expect(options.method).toBeUndefined();
    expect(options.headers).toEqual({ "Content-Type": "application/json" });
  });

  it("POST sends method and a JSON body", async () => {
    const fetchMock = mockFetch(201, { trade_id: "abc" });
    vi.stubGlobal("fetch", fetchMock);

    const data = await api.post("/trades", { currency_pair: "EURUSD" });

    expect(data).toEqual({ trade_id: "abc" });
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toContain("/trades");
    expect(options.method).toBe("POST");
    expect(options.body).toBe('{"currency_pair":"EURUSD"}');
  });

  it("throws ApiError with status on a non-2xx response", async () => {
    vi.stubGlobal("fetch", mockFetch(422, { detail: "bad" }));

    await expect(api.get("/trades")).rejects.toMatchObject({
      name: "ApiError",
      status: 422,
    });
  });

  it("throws ApiError when the network is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("failed")));

    await expect(api.get("/trades")).rejects.toMatchObject({ status: 0 });
  });
});
