const assert = require("assert");
const PricingEngine = require("../src/pricingEngine");

function closeTo(actual, expected, tolerance = 0.02) {
  assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} is not within ${tolerance} of ${expected}`);
}

const deckSample = {
  material: "453561181211",
  equipmentEquivalent: "FUS7445",
  country: "DE",
  salesOrg: "DX36",
  modality: "Ultrasound",
  currentCountryListPrice: "44914.95",
  countryTargetPrice: "19172",
  serviceAddedValuePct: "11.28",
  discountPolicyPct: "5",
  costPrice: "4319.08",
  minimumMarginPct: "44.73684211",
  exchangeRate: "1",
  noReturnPenaltyPct: "100",
  roundingUnit: "5",
  effectiveDate: "2026-07-01",
  productHierarchy: "HS-US-EPIQ",
};

const result = PricingEngine.calculateEquipmentEquivalent(deckSample);
assert.strictEqual(result.status, "ready");
closeTo(result.calculated.servicePartsTargetPrice, 21334.6);
closeTo(result.calculated.servicePartsCountryListPrice, 22457.47, 0.05);
closeTo(result.calculated.minimumMarginPrice, 7815.48, 0.05);
closeTo(result.calculated.noReturnPenaltyAmount, 22457.47, 0.05);
closeTo(result.calculated.unroundedFutureListPrice, 44914.95, 0.05);
assert.strictEqual(result.calculated.finalApprovedPrice, 44915);
assert.strictEqual(result.calculated.marginStatus, "pass");

const invalid = PricingEngine.calculateEquipmentEquivalent({
  ...deckSample,
  countryTargetPrice: "",
});
assert.strictEqual(invalid.status, "error");
assert.ok(invalid.errors.includes("countryTargetPrice is required"));

const pendingRequest = {
  approvalStatus: "Pending Approval",
  lines: [result],
};
assert.throws(() => PricingEngine.createSapReleaseBatch(pendingRequest, "Category Leader"), /approved/);

const approvedRequest = {
  approvalStatus: "Approved",
  lines: [result, invalid],
};
const batch = PricingEngine.createSapReleaseBatch(approvedRequest, "Category Leader");
assert.deepStrictEqual(batch.conditionTypes, ["ZCS1", "ZCS5"]);
assert.strictEqual(batch.results[0].zcs1Status, "Success");
assert.strictEqual(batch.results[1].zcs1Status, "Blocked");
assert.strictEqual(batch.status, "Completed with blocks");

const many = Array.from({ length: 3000 }, (_, index) => ({
  ...deckSample,
  material: `SIM${index}`,
}));
const calculated = PricingEngine.calculateLines(many);
assert.strictEqual(calculated.length, 3000);
assert.strictEqual(calculated[2999].calculated.finalApprovedPrice, 44915);

console.log("pricingEngine tests passed");
