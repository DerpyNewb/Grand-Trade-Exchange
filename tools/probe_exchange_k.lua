-- CONCENTRATION_K calibration read. STRICTLY READ-ONLY: it never touches EX.current,
-- EX.med or EX.pressure, and it never sets a saved value. One Lua error wedges the
-- bridge for the whole game session, so the entire body is inside a pcall.
local ok, res = pcall(function()
    if not EX then return "EX is nil - the exchange script never loaded" end
    if not EX.supply then EX.rescan() end
    local supply, owners = EX.supply, EX.owners or {}
    if not supply then return "no supply scan - EX.rescan() produced nothing" end

    local KS = { 0, 1, 3, 10 }

    -- Local, so EX.CONCENTRATION_K is never mutated. Same arithmetic as EX.effective_supply.
    local function eff_at(raw, h, k) return raw / (1 + k * h) end

    -- The median is over EFFECTIVE supplies, so it MOVES with K. Comparing rungs across K
    -- against one fixed median would measure nothing: concentration is purely relative here,
    -- and a board-wide K change mostly cancels out through the median. That cancellation is
    -- exactly what this read is for.
    local med, raws = {}, {}
    for _, k in ipairs(KS) do
        local counts = {}
        for _, r in ipairs(EX.COMMODITIES) do
            counts[#counts + 1] = eff_at(supply[r] or 0, EX.hhi(owners[r] or {}), k)
        end
        med[k] = EX.median(counts)
    end
    for _, r in ipairs(EX.COMMODITIES) do raws[#raws + 1] = supply[r] or 0 end

    local out = {}
    out[#out + 1] = "raw median " .. EX.median(raws)
    local mline = "eff median  "
    for _, k in ipairs(KS) do
        mline = mline .. string.format("K=%-2d %-9.2f", k, med[k])
    end
    out[#out + 1] = mline
    out[#out + 1] = "res                raw   hhi    own"
        .. "   |  rung/price at K=0, 1, 3, 10   | press"

    for _, r in ipairs(EX.COMMODITIES) do
        local raw = supply[r] or 0
        local h = EX.hhi(owners[r] or {})
        local nown = 0
        for _ in pairs(owners[r] or {}) do nown = nown + 1 end
        local line = string.format("%-18s %4d  %.3f  %4d  |", r, raw, h, nown)
        for _, k in ipairs(KS) do
            -- base rung only: the pressure shift is our own trading, not concentration.
            local rung = EX.ladder_index(EX.price_multiplier(eff_at(raw, h, k), med[k]))
            if rung < 1 then rung = 1 elseif rung > EX.RUNGS then rung = EX.RUNGS end
            line = line .. string.format(" %2d/%-5d", rung, EX.price_at(rung))
        end
        out[#out + 1] = line .. string.format(" | %d", EX.pressure[r] or 0)
    end

    -- A rung pinned at 1 or 42 is a commodity the ladder cannot price: it is off the end,
    -- and no K retune moves it back on. Counted per K so the clamp is visible as a number.
    for _, k in ipairs(KS) do
        local lo, hi = 0, 0
        for _, r in ipairs(EX.COMMODITIES) do
            local rung = EX.ladder_index(EX.price_multiplier(
                eff_at(supply[r] or 0, EX.hhi(owners[r] or {}), k), med[k]))
            if rung <= 1 then lo = lo + 1 elseif rung >= EX.RUNGS then hi = hi + 1 end
        end
        out[#out + 1] = string.format("K=%-2d clamped: %d at rung 1, %d at rung %d",
                                      k, lo, hi, EX.RUNGS)
    end

    out[#out + 1] = "turn " .. cm:model():turn_number()
        .. "  live K=" .. EX.CONCENTRATION_K
        .. "  (unchanged - this read mutates nothing)"
    return table.concat(out, "\n")
end)
return ok and res or ("PROBE FAILED: " .. tostring(res))
