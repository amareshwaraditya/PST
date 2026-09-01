(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.PricingEngine = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  const POC_SCOPE = Object.freeze({
    salesOrg: "DX36",
    modality: "Ultrasound",
    pricingStrategy: "Equipment Equivalent",
  });

  const REQUIRED_FIELDS = [
    "material",
    "equipmentEquivalent",
    "country",
    "salesOrg",
    "modality",
    "countryTargetPrice",
    "serviceAddedValuePct",
    "discountPolicyPct",
    "costPrice",
    "minimumMarginPct",
    "exchangeRate",
    "noReturnPenaltyPct",
    "roundingUnit",
    "effectiveDate",
  ];

  function toNumber(value, fallback = 0) {
    if (value === null || value === undefined || value === "") return fallback;
    const normalized = String(value).replace(/,/g, "").replace(/%$/, "").trim();
    const number = Number(normalized);
    return Number.isFinite(number) ? number : fallback;
  }

  function normalizePercent(value) {
    const number = toNumber(value);
    return Math.abs(number) > 1 ? number / 100 : number;
  }

  function roundToCurrency(value) {
    return Math.round((Number(value) + Number.EPSILON) * 100) / 100;
  }

  function roundUpToUnit(value, unit) {
    const roundingUnit = toNumber(unit, 1);
    if (roundingUnit <= 0) return roundToCurrency(value);
    return roundToCurrency(Math.ceil(value / roundingUnit) * roundingUnit);
  }

  function validateLine(line) {
    const errors = [];
    const warnings = [];

    REQUIRED_FIELDS.forEach((field) => {
      if (line[field] === undefined || line[field] === null || String(line[field]).trim() === "") {
        errors.push(`${field} is required`);
      }
    });

    if (line.salesOrg && line.salesOrg !== POC_SCOPE.salesOrg) {
      errors.push(`salesOrg must be ${POC_SCOPE.salesOrg}`);
    }

    if (line.modality && line.modality !== POC_SCOPE.modality) {
      errors.push(`modality must be ${POC_SCOPE.modality}`);
    }

    const numericFields = [
      "countryTargetPrice",
      "serviceAddedValuePct",
      "discountPolicyPct",
      "costPrice",
      "minimumMarginPct",
      "exchangeRate",
      "noReturnPenaltyPct",
      "roundingUnit",
    ];

    numericFields.forEach((field) => {
      if (line[field] !== undefined && line[field] !== "" && !Number.isFinite(toNumber(line[field], NaN))) {
        errors.push(`${field} must be numeric`);
      }
    });

    if (normalizePercent(line.discountPolicyPct) >= 1) {
      errors.push("discountPolicyPct must be below 100%");
    }

    if (normalizePercent(line.minimumMarginPct) >= 1) {
      errors.push("minimumMarginPct must be below 100%");
    }

    if (toNumber(line.exchangeRate, 1) <= 0) {
      errors.push("exchangeRate must be greater than 0");
    }

    if (toNumber(line.roundingUnit, 1) <= 0) {
      errors.push("roundingUnit must be greater than 0");
    }

    if (!line.productHierarchy) {
      warnings.push("productHierarchy missing; latest maintained master data should be checked");
    }

    return {
      status: errors.length ? "error" : warnings.length ? "warning" : "ready",
      errors,
      warnings,
    };
  }

  function calculateEquipmentEquivalent(line) {
    const validation = validateLine(line);
    const countryTargetPrice = toNumber(line.countryTargetPrice);
    const serviceAddedValuePct = normalizePercent(line.serviceAddedValuePct);
    const discountPolicyPct = normalizePercent(line.discountPolicyPct);
    const costPrice = toNumber(line.costPrice);
    const minimumMarginPct = normalizePercent(line.minimumMarginPct);
    const exchangeRate = toNumber(line.exchangeRate, 1);
    const noReturnPenaltyPct = normalizePercent(line.noReturnPenaltyPct);
    const roundingUnit = toNumber(line.roundingUnit, 1);
    const currentListPrice = toNumber(line.currentCountryListPrice);

    const servicePartsTargetPrice = countryTargetPrice * (1 + serviceAddedValuePct);
    const servicePartsCountryListPrice = (servicePartsTargetPrice / (1 - discountPolicyPct)) * exchangeRate;
    const minimumMarginPrice = (costPrice / (1 - minimumMarginPct)) * exchangeRate;
    const noReturnPenaltyAmount = servicePartsCountryListPrice * noReturnPenaltyPct;
    const unroundedFutureListPrice = servicePartsCountryListPrice + noReturnPenaltyAmount;
    const finalApprovedPrice = roundUpToUnit(unroundedFutureListPrice, roundingUnit);
    const marginStatus = servicePartsCountryListPrice >= minimumMarginPrice ? "pass" : "fail";
    const contributionMarginPct = finalApprovedPrice === 0 ? 0 : (finalApprovedPrice - costPrice * exchangeRate) / finalApprovedPrice;
    const priceChangePct = currentListPrice === 0 ? 0 : (finalApprovedPrice - currentListPrice) / currentListPrice;

    return {
      material: line.material || "",
      equipmentEquivalent: line.equipmentEquivalent || "",
      country: line.country || "",
      salesOrg: line.salesOrg || "",
      modality: line.modality || "",
      effectiveDate: line.effectiveDate || "",
      source: {
        currentCountryListPrice: roundToCurrency(currentListPrice),
        countryTargetPrice: roundToCurrency(countryTargetPrice),
        serviceAddedValuePct,
        discountPolicyPct,
        costPrice: roundToCurrency(costPrice),
        minimumMarginPct,
        exchangeRate,
        noReturnPenaltyPct,
        roundingUnit,
        productHierarchy: line.productHierarchy || "",
      },
      calculated: {
        servicePartsTargetPrice: roundToCurrency(servicePartsTargetPrice),
        servicePartsCountryListPrice: roundToCurrency(servicePartsCountryListPrice),
        minimumMarginPrice: roundToCurrency(minimumMarginPrice),
        noReturnPenaltyAmount: roundToCurrency(noReturnPenaltyAmount),
        unroundedFutureListPrice: roundToCurrency(unroundedFutureListPrice),
        roundingAdjustment: roundToCurrency(finalApprovedPrice - unroundedFutureListPrice),
        finalApprovedPrice,
        contributionMarginPct: roundToCurrency(contributionMarginPct * 100),
        priceChangePct: roundToCurrency(priceChangePct * 100),
        marginStatus,
      },
      status: validation.status,
      errors: validation.errors,
      warnings: validation.warnings,
      approvalStatus: "Draft",
      sapUpdateStatus: "Not staged",
    };
  }

  function calculateLines(lines, onProgress) {
    const results = [];
    lines.forEach((line, index) => {
      results.push(calculateEquipmentEquivalent(line));
      if (onProgress && (index + 1) % 500 === 0) {
        onProgress(index + 1, lines.length);
      }
    });
    if (onProgress) onProgress(lines.length, lines.length);
    return results;
  }

  function calculateLinesPartitioned(lines, options = {}) {
    const batchSize = options.batchSize || 1000;
    const onProgress = options.onProgress || function () {};
    const results = [];
    let cursor = 0;

    return new Promise((resolve) => {
      function processBatch() {
        const end = Math.min(cursor + batchSize, lines.length);
        for (let index = cursor; index < end; index += 1) {
          results.push(calculateEquipmentEquivalent(lines[index]));
        }
        cursor = end;
        onProgress(cursor, lines.length);
        if (cursor < lines.length) {
          setTimeout(processBatch, 0);
        } else {
          resolve(results);
        }
      }
      processBatch();
    });
  }

  function createSapReleaseBatch(masterRequest, approvedBy) {
    if (!masterRequest || masterRequest.approvalStatus !== "Approved") {
      throw new Error("Master request must be approved before SAP update");
    }

    const batchId = `SAP-${Date.now()}`;
    const results = masterRequest.lines.map((line, index) => {
      if (line.status === "error") {
        return {
          lineNumber: index + 1,
          material: line.material,
          zcs1Status: "Blocked",
          zcs5Status: "Blocked",
          message: line.errors.join("; "),
        };
      }

      return {
        lineNumber: index + 1,
        material: line.material,
        zcs1: line.calculated.finalApprovedPrice,
        zcs5: line.calculated.noReturnPenaltyAmount,
        zcs1Status: "Success",
        zcs5Status: "Success",
        message: `Posted by ${approvedBy}`,
      };
    });

    return {
      batchId,
      createdAt: new Date().toISOString(),
      approvedBy,
      conditionTypes: ["ZCS1", "ZCS5"],
      results,
      status: results.some((result) => result.zcs1Status === "Blocked") ? "Completed with blocks" : "Completed",
    };
  }

  return {
    POC_SCOPE,
    REQUIRED_FIELDS,
    calculateEquipmentEquivalent,
    calculateLines,
    calculateLinesPartitioned,
    createSapReleaseBatch,
    normalizePercent,
    roundToCurrency,
    roundUpToUnit,
    toNumber,
    validateLine,
  };
});
