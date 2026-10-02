/**
 * Display labels for the proposal form's enums.
 *
 * Deliberately a copy of the vocabularies in the proposal app
 * (`aimdl-projects/src/constants/project.ts`) rather than an import: the two front ends
 * share no build. The server's `project_schema` is what keeps them honest -- a value that
 * reaches here has already passed its enum -- and an unknown key falls back to the raw
 * value, so a drifting label never hides a proposal's answer.
 */

const ACCESS_CATEGORY = {
    jhu: 'Johns Hopkins University',
    'external-academic': 'External (academic / not-for-profit)',
    'external-corporate': 'External (corporate / industrial)',
    'external-government': 'External (government)',
    'external-foreign': 'External (foreign, non-US)'
};

const DATA_CLASSIFICATION = {
    open: 'Open (fundamental research)',
    'confidential-proprietary': 'Confidential / proprietary',
    'confidential-controlled': 'Confidential / controlled (export restrictions and/or CUI)',
    'opt-out': 'Opt-out (restrictions on dissemination)'
};

const PROJECT_TYPE = {
    integrated: 'Integrated project',
    singleInstrument: 'Single-instrument project',
    development: 'Development project'
};

const MEMBER_STATUS = {
    faculty: 'Faculty / senior investigator',
    staff: 'Staff',
    postdoc: 'Post-doc',
    grad: 'Graduate student',
    undergrad: 'Undergraduate',
    other: 'Other'
};

const ROLE = {
    PI: 'Full access (PI)',
    manager: 'Can add and edit data',
    user: 'Can view data'
};

const SAMPLE_HAZARD = {
    none: 'None',
    toxic: 'Toxic',
    flammable: 'Flammable',
    energetic: 'Energetic',
    biosafety: 'Biosafety',
    radioactive: 'Radioactive',
    other: 'Other'
};

const OTHER_HAZARD = {
    none: 'None',
    laser: 'Laser (class 3-4)',
    'high-temperature': 'High temperature',
    'high-voltage': 'High voltage',
    'user-equipment': 'Custom or user-supplied equipment'
};

/** Hazards that normally need separate institutional approval before work can start. */
const NEEDS_APPROVAL = ['biosafety', 'radioactive'];

const label = (map) => (value) => map[value] || value || '';
const labels = (map) => (values) => (values || []).map(label(map));
const hazards = (safety) => []
    .concat((safety && safety.sampleHazards) || [], (safety && safety.otherHazards) || []);

export default {
    accessCategory: label(ACCESS_CATEGORY),
    dataClassification: label(DATA_CLASSIFICATION),
    projectType: label(PROJECT_TYPE),
    memberStatus: label(MEMBER_STATUS),
    role: label(ROLE),
    sampleHazards: labels(SAMPLE_HAZARD),
    otherHazards: labels(OTHER_HAZARD),
    hazardsDeclared: (safety) => hazards(safety).some((h) => h !== 'none'),
    needsApproval: (safety) => (((safety && safety.sampleHazards) || [])
        .some((h) => NEEDS_APPROVAL.indexOf(h) !== -1))
};
