import { describe, it, expect } from "vitest";
import { act, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderHookWithQuery } from "@/test/render";
import {
  useCompany,
  useCompanyDividends,
  useCompanyFinancials,
  useCompanyFinancialsPivoted,
  useCompanyPrices,
  useCompanySearch,
  useCompanySnapshots,
  useEarningsDates,
  useIndustries,
  useInstitutionalHolders,
  useMarketHierarchy,
  useOptionsChain,
  useOptionsExpiries,
  useSectors,
  useShortInterest,
  useSyncCompanyYF,
} from "@/hooks/useCompanies";
import {
  MOCK_COMPANY,
  MOCK_DIVIDEND,
  MOCK_EARNINGS_DATE,
  MOCK_FINANCIAL,
  MOCK_INSTITUTIONAL_HOLDERS,
  MOCK_MARKET_HIERARCHY,
  MOCK_OPTIONS_CHAIN,
  MOCK_PAGINATED_COMPANIES,
  MOCK_PAGINATED_DIVIDENDS,
  MOCK_PAGINATED_EARNINGS,
  MOCK_PAGINATED_FINANCIALS,
  MOCK_PAGINATED_INDUSTRIES,
  MOCK_PAGINATED_OPTIONS_EXPIRIES,
  MOCK_PAGINATED_PRICES,
  MOCK_PAGINATED_SECTORS,
  MOCK_PAGINATED_SHORT_INTEREST,
  MOCK_PAGINATED_SNAPSHOTS,
  MOCK_PIVOTED_FINANCIALS,
  MOCK_PRICE_BAR,
  MOCK_SHORT_INTEREST,
  MOCK_SNAPSHOT,
} from "@/test/handlers";

const BASE = "http://localhost:8004";

describe("useCompanySearch", () => {
  it("returns paginated companies", async () => {
    server.use(
      http.get(`${BASE}/api/companies/`, () =>
        HttpResponse.json(MOCK_PAGINATED_COMPANIES),
      ),
    );
    const { result } = renderHookWithQuery(() => useCompanySearch());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.results[0].symbol).toBe("AAPL");
  });
});

describe("useCompany", () => {
  it("returns a single company by id", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/`, () => HttpResponse.json(MOCK_COMPANY)),
    );
    const { result } = renderHookWithQuery(() => useCompany(MOCK_COMPANY.id));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.name).toBe("Apple Inc.");
  });

  it("stays idle when id is falsy", () => {
    const { result } = renderHookWithQuery(() => useCompany(""));
    expect(result.current.fetchStatus).toBe("idle");
  });
});

describe("useSyncCompanyYF", () => {
  it("resolves with company data on success", async () => {
    server.use(
      http.post(`${BASE}/api/companies/yf/sync/:symbol/`, () =>
        HttpResponse.json(MOCK_COMPANY),
      ),
    );
    const { result } = renderHookWithQuery(() => useSyncCompanyYF());
    act(() => {
      result.current.mutate("AAPL");
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.symbol).toBe("AAPL");
  });

  it("is error on 404", async () => {
    server.use(
      http.post(`${BASE}/api/companies/yf/sync/:symbol/`, () =>
        HttpResponse.json({ detail: "Not found." }, { status: 404 }),
      ),
    );
    const { result } = renderHookWithQuery(() => useSyncCompanyYF());
    act(() => {
      result.current.mutate("ZZZZZ");
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useCompanySnapshots", () => {
  it("returns paginated snapshots for a company", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/snapshots/`, () =>
        HttpResponse.json(MOCK_PAGINATED_SNAPSHOTS),
      ),
    );
    const { result } = renderHookWithQuery(() => useCompanySnapshots(MOCK_COMPANY.id));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.results[0]).toEqual(MOCK_SNAPSHOT);
    expect(result.current.data?.count).toBe(1);
  });

  it("stays idle when companyId is falsy", () => {
    const { result } = renderHookWithQuery(() => useCompanySnapshots(0));
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("returns trailing_pe from snapshot", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/snapshots/`, () =>
        HttpResponse.json(MOCK_PAGINATED_SNAPSHOTS),
      ),
    );
    const { result } = renderHookWithQuery(() => useCompanySnapshots(MOCK_COMPANY.id));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.results[0].trailing_pe).toBe(MOCK_SNAPSHOT.trailing_pe);
  });
});

describe("useCompanyFinancials", () => {
  it("returns paginated financials for a company", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/financials/`, () =>
        HttpResponse.json(MOCK_PAGINATED_FINANCIALS),
      ),
    );
    const { result } = renderHookWithQuery(() => useCompanyFinancials(MOCK_COMPANY.id));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.results[0]).toEqual(MOCK_FINANCIAL);
  });

  it("stays idle when companyId is falsy", () => {
    const { result } = renderHookWithQuery(() => useCompanyFinancials(0));
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("is error on 500", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/financials/`, () =>
        HttpResponse.json({ detail: "Server error." }, { status: 500 }),
      ),
    );
    const { result } = renderHookWithQuery(() => useCompanyFinancials(MOCK_COMPANY.id));
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useCompanyPrices", () => {
  it("returns paginated prices for a company", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/prices/`, () =>
        HttpResponse.json(MOCK_PAGINATED_PRICES),
      ),
    );
    const { result } = renderHookWithQuery(() => useCompanyPrices(MOCK_COMPANY.id));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.results[0]).toEqual(MOCK_PRICE_BAR);
    expect(result.current.data?.count).toBe(1);
  });

  it("stays idle when companyId is falsy", () => {
    const { result } = renderHookWithQuery(() => useCompanyPrices(0));
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("returns OHLCV fields", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/prices/`, () =>
        HttpResponse.json(MOCK_PAGINATED_PRICES),
      ),
    );
    const { result } = renderHookWithQuery(() => useCompanyPrices(MOCK_COMPANY.id));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const bar = result.current.data!.results[0];
    expect(bar.open).toBeDefined();
    expect(bar.high).toBeDefined();
    expect(bar.low).toBeDefined();
    expect(bar.close).toBeDefined();
    expect(bar.volume).toBeDefined();
  });

  it("forwards page param to the API", async () => {
    let capturedPage: string | null = null;
    server.use(
      http.get(`${BASE}/api/companies/:id/prices/`, ({ request }) => {
        capturedPage = new URL(request.url).searchParams.get("page");
        return HttpResponse.json(MOCK_PAGINATED_PRICES);
      }),
    );
    const { result } = renderHookWithQuery(() =>
      useCompanyPrices(MOCK_COMPANY.id, { page: 3 }),
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(capturedPage).toBe("3");
  });
});

describe("useCompanyDividends", () => {
  it("returns paginated dividends for a company", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/dividends/`, () =>
        HttpResponse.json(MOCK_PAGINATED_DIVIDENDS),
      ),
    );
    const { result } = renderHookWithQuery(() => useCompanyDividends(MOCK_COMPANY.id));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.results[0]).toEqual(MOCK_DIVIDEND);
  });

  it("stays idle when companyId is falsy", () => {
    const { result } = renderHookWithQuery(() => useCompanyDividends(0));
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("returns empty results when no dividends", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/dividends/`, () =>
        HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
      ),
    );
    const { result } = renderHookWithQuery(() => useCompanyDividends(MOCK_COMPANY.id));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.results).toHaveLength(0);
  });
});

describe("useSectors", () => {
  it("returns paginated sectors", async () => {
    server.use(
      http.get(`${BASE}/api/companies/sectors/`, () =>
        HttpResponse.json(MOCK_PAGINATED_SECTORS),
      ),
    );
    const { result } = renderHookWithQuery(() => useSectors());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.results[0].name).toBe("Technology");
  });

  it("returns company_count from sector", async () => {
    server.use(
      http.get(`${BASE}/api/companies/sectors/`, () =>
        HttpResponse.json(MOCK_PAGINATED_SECTORS),
      ),
    );
    const { result } = renderHookWithQuery(() => useSectors());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.results[0].company_count).toBe(5);
  });

  it("returns industry_count from sector", async () => {
    server.use(
      http.get(`${BASE}/api/companies/sectors/`, () =>
        HttpResponse.json(MOCK_PAGINATED_SECTORS),
      ),
    );
    const { result } = renderHookWithQuery(() => useSectors());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.results[0].industry_count).toBe(2);
  });

  it("is error on 500", async () => {
    server.use(
      http.get(`${BASE}/api/companies/sectors/`, () =>
        HttpResponse.json({ detail: "Server error." }, { status: 500 }),
      ),
    );
    const { result } = renderHookWithQuery(() => useSectors());
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useIndustries", () => {
  it("returns paginated industries", async () => {
    server.use(
      http.get(`${BASE}/api/companies/industries/`, () =>
        HttpResponse.json(MOCK_PAGINATED_INDUSTRIES),
      ),
    );
    const { result } = renderHookWithQuery(() => useIndustries());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.results[0].name).toBe("Consumer Electronics");
  });

  it("returns company_count from industry", async () => {
    server.use(
      http.get(`${BASE}/api/companies/industries/`, () =>
        HttpResponse.json(MOCK_PAGINATED_INDUSTRIES),
      ),
    );
    const { result } = renderHookWithQuery(() => useIndustries());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.results[0].company_count).toBe(3);
  });

  it("passes sector filter param through", async () => {
    let capturedUrl = "";
    server.use(
      http.get(`${BASE}/api/companies/industries/`, ({ request }) => {
        capturedUrl = request.url;
        return HttpResponse.json(MOCK_PAGINATED_INDUSTRIES);
      }),
    );
    const { result } = renderHookWithQuery(() => useIndustries({ sector: 1 }));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(capturedUrl).toContain("sector=1");
  });
});

describe("useMarketHierarchy", () => {
  it("returns market hierarchy data", async () => {
    server.use(
      http.get(`${BASE}/api/companies/market-hierarchy/`, () =>
        HttpResponse.json(MOCK_MARKET_HIERARCHY),
      ),
    );
    const { result } = renderHookWithQuery(() => useMarketHierarchy());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.[0].name).toBe("Technology");
  });

  it("returns nested children", async () => {
    server.use(
      http.get(`${BASE}/api/companies/market-hierarchy/`, () =>
        HttpResponse.json(MOCK_MARKET_HIERARCHY),
      ),
    );
    const { result } = renderHookWithQuery(() => useMarketHierarchy());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.[0].children?.length).toBeGreaterThan(0);
  });

  it("is error on 500", async () => {
    server.use(
      http.get(`${BASE}/api/companies/market-hierarchy/`, () =>
        HttpResponse.json({ detail: "error" }, { status: 500 }),
      ),
    );
    const { result } = renderHookWithQuery(() => useMarketHierarchy());
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useCompanyFinancialsPivoted", () => {
  it("returns pivoted financials", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/financials/pivoted/`, () =>
        HttpResponse.json(MOCK_PIVOTED_FINANCIALS),
      ),
    );
    const { result } = renderHookWithQuery(() =>
      useCompanyFinancialsPivoted(MOCK_COMPANY.id),
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.dates).toEqual(["2023-12-31", "2022-12-31"]);
    expect(result.current.data?.rows[0].metric).toBe("Total Revenue");
  });

  it("stays idle when companyId is falsy", () => {
    const { result } = renderHookWithQuery(() => useCompanyFinancialsPivoted(0));
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("passes statement_type param through", async () => {
    let capturedUrl = "";
    server.use(
      http.get(`${BASE}/api/companies/:id/financials/pivoted/`, ({ request }) => {
        capturedUrl = request.url;
        return HttpResponse.json(MOCK_PIVOTED_FINANCIALS);
      }),
    );
    const { result } = renderHookWithQuery(() =>
      useCompanyFinancialsPivoted(MOCK_COMPANY.id, { statement_type: "income" }),
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(capturedUrl).toContain("statement_type=income");
  });

  it("passes period param through", async () => {
    let capturedUrl = "";
    server.use(
      http.get(`${BASE}/api/companies/:id/financials/pivoted/`, ({ request }) => {
        capturedUrl = request.url;
        return HttpResponse.json(MOCK_PIVOTED_FINANCIALS);
      }),
    );
    const { result } = renderHookWithQuery(() =>
      useCompanyFinancialsPivoted(MOCK_COMPANY.id, { period: "quarterly" }),
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(capturedUrl).toContain("period=quarterly");
  });
});

describe("useShortInterest", () => {
  it("returns paginated short interest records", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/short-interest/`, () =>
        HttpResponse.json(MOCK_PAGINATED_SHORT_INTEREST),
      ),
    );
    const { result } = renderHookWithQuery(() => useShortInterest(MOCK_COMPANY.id));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.results[0]).toEqual(MOCK_SHORT_INTEREST);
  });

  it("stays idle when companyId is falsy", () => {
    const { result } = renderHookWithQuery(() => useShortInterest(0));
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("returns short_ratio field", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/short-interest/`, () =>
        HttpResponse.json(MOCK_PAGINATED_SHORT_INTEREST),
      ),
    );
    const { result } = renderHookWithQuery(() => useShortInterest(MOCK_COMPANY.id));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.results[0].short_ratio).toBe(MOCK_SHORT_INTEREST.short_ratio);
  });
});

describe("useInstitutionalHolders", () => {
  it("returns a single institutional holder snapshot", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/institutional-holders/`, () =>
        HttpResponse.json(MOCK_INSTITUTIONAL_HOLDERS),
      ),
    );
    const { result } = renderHookWithQuery(() => useInstitutionalHolders(MOCK_COMPANY.id));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.holders).toHaveLength(2);
  });

  it("stays idle when companyId is falsy", () => {
    const { result } = renderHookWithQuery(() => useInstitutionalHolders(0));
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("returns holder name from first entry", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/institutional-holders/`, () =>
        HttpResponse.json(MOCK_INSTITUTIONAL_HOLDERS),
      ),
    );
    const { result } = renderHookWithQuery(() => useInstitutionalHolders(MOCK_COMPANY.id));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.holders[0].holder).toBe("Vanguard Group Inc");
  });
});

describe("useEarningsDates", () => {
  it("returns paginated earnings dates", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/earnings-dates/`, () =>
        HttpResponse.json(MOCK_PAGINATED_EARNINGS),
      ),
    );
    const { result } = renderHookWithQuery(() => useEarningsDates(MOCK_COMPANY.id));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.count).toBe(2);
  });

  it("stays idle when companyId is falsy", () => {
    const { result } = renderHookWithQuery(() => useEarningsDates(0));
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("returns upcoming flag on first record", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/earnings-dates/`, () =>
        HttpResponse.json(MOCK_PAGINATED_EARNINGS),
      ),
    );
    const { result } = renderHookWithQuery(() => useEarningsDates(MOCK_COMPANY.id));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.results[0]).toEqual(MOCK_EARNINGS_DATE);
  });

  it("passes is_upcoming filter param through", async () => {
    let capturedUrl = "";
    server.use(
      http.get(`${BASE}/api/companies/:id/earnings-dates/`, ({ request }) => {
        capturedUrl = request.url;
        return HttpResponse.json(MOCK_PAGINATED_EARNINGS);
      }),
    );
    const { result } = renderHookWithQuery(() =>
      useEarningsDates(MOCK_COMPANY.id, { is_upcoming: true }),
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(capturedUrl).toContain("is_upcoming=true");
  });
});

describe("useOptionsExpiries", () => {
  it("returns paginated expiry dates", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/options/`, () =>
        HttpResponse.json(MOCK_PAGINATED_OPTIONS_EXPIRIES),
      ),
    );
    const { result } = renderHookWithQuery(() => useOptionsExpiries(MOCK_COMPANY.id));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.results[0].expiry_date).toBe("2026-06-20");
  });

  it("stays idle when companyId is falsy", () => {
    const { result } = renderHookWithQuery(() => useOptionsExpiries(0));
    expect(result.current.fetchStatus).toBe("idle");
  });
});

describe("useOptionsChain", () => {
  it("returns calls and puts for a given expiry", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/options/:expiryDate/`, () =>
        HttpResponse.json(MOCK_OPTIONS_CHAIN),
      ),
    );
    const { result } = renderHookWithQuery(() =>
      useOptionsChain(MOCK_COMPANY.id, "2026-06-20"),
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.calls).toHaveLength(1);
    expect(result.current.data?.puts).toHaveLength(1);
  });

  it("stays idle when expiryDate is null", () => {
    const { result } = renderHookWithQuery(() => useOptionsChain(MOCK_COMPANY.id, null));
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("stays idle when companyId is falsy", () => {
    const { result } = renderHookWithQuery(() => useOptionsChain(0, "2026-06-20"));
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("returns in_the_money on call contract", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/options/:expiryDate/`, () =>
        HttpResponse.json(MOCK_OPTIONS_CHAIN),
      ),
    );
    const { result } = renderHookWithQuery(() =>
      useOptionsChain(MOCK_COMPANY.id, "2026-06-20"),
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.calls[0].in_the_money).toBe(true);
  });
});
