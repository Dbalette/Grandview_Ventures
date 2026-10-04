/* Reference data: population norms for the "average face" comparison, and published celebrity scores.
   Every number here is quoted from the literature; the methodology page carries the citations. */
import { IRIS_DIAMETER_MM } from './phi.js';
export { IRIS_DIAMETER_MM };

/** Farkas soft-tissue anthropometry, North American White young adults (18-25 y), direct caliper measurements, in mm.
 *  Sources: Farkas, Anthropometry of the Head and Face (1994), Appendix A; Farkas et al. 2005, J Craniofac Surg 16(4):615-646.
 *  Values collated from secondary reports (see methodology). Items marked approx are not verified to the decimal. */
export const FARKAS = {
  female: {
    key: 'female', label: 'Average young woman', n: 200,
    trGn: 173.3, nGn: 111.8, nSn: 48.9, snGn: 65.5, snSto: 20.1, stoGn: 43.4,
    zyZy: 129.9, goGo: 91.1, exEx: 86.8, enEn: 31.6, exEn: 30.7, pp: 61.0, alAl: 31.4, chCh: 50.2, nPrn: 44.7,
  },
  male: {
    key: 'male', label: 'Average young man', n: 109,
    trGn: 187.2, nGn: 121.3, nSn: 53.0, snGn: 71.9, snSto: 22.3, stoGn: 50.7,
    zyZy: 137.1, goGo: 97.1, exEx: 89.4, enEn: 32.9, exEn: 31.3, pp: 64.0, alAl: 34.7 /* approx */, chCh: 53.3, nPrn: 50.0,
  },
};

/** Vertical offsets the caliper tables do not give directly, taken from the geometry of the face mesh (mm):
 *  the brow point (glabella) sits above the nasion, the pupils a little below it, the nostril base and the
 *  nose tip above the subnasale. These are documented approximations, used only for the reference face. */
export const DERIVED_OFFSETS = { glabellaAboveNasion: 15, pupilsBelowNasion: 5, alarBaseAboveSubnasale: 12, noseTipAboveSubnasale: 9 };

/** Named distances for a reference face, in the shape phi.js metricsFromDistances() expects. */
export function referenceDistances(sexKey) {
  const f = FARKAS[sexKey];
  const o = DERIVED_OFFSETS;
  return {
    faceLength: f.trGn, faceWidth: f.zyZy, mouthWidth: f.chCh, noseWidth: f.alAl, noseLength: f.nSn,
    outerEyeSpan: f.exEx, innerEyeSpan: f.enEn, eyeWidth: f.exEn, interpupillary: f.pp,
    glabellaToSubnasale: f.nSn + o.glabellaAboveNasion,
    subnasaleToMenton: f.snGn,
    eyesToStomion: f.nSn - o.pupilsBelowNasion + f.snSto,
    alarToStomion: o.alarBaseAboveSubnasale + f.snSto,
    noseTipToMenton: o.noseTipAboveSubnasale + f.snGn,
    stomionToMenton: f.stoGn,
    subnasaleToStomion: f.snSto,
  };
}

/** Typical left-right asymmetry index of a normal face, in percent. Farkas & Cheung (1981): differences under 3% are indiscernible. */
export const REFERENCE_ASYMMETRY_PERCENT = 2.0;

/** Scores published in the press from Dr Julian De Silva's "Golden Ratio of Beauty Phi" face mapping.
 *  His measurements and weights are unpublished, so these are not on exactly the same scale as the mirror's; shown for flavour. */
export const BENCHMARKS = [
  { name: 'Emma Stone', score: 94.72, year: 2025 },
  { name: 'Jodie Comer', score: 94.52, year: 2022 },
  { name: 'Zendaya', score: 94.37, year: 2022 },
  { name: 'Bella Hadid', score: 94.35, year: 2019 },
  { name: 'Regé-Jean Page', score: 93.65, year: 2021 },
  { name: 'Chris Hemsworth', score: 93.53, year: 2021 },
  { name: 'Beyoncé', score: 92.44, year: 2019 },
  { name: 'Robert Pattinson', score: 92.15, year: 2020 },
  { name: 'George Clooney', score: 91.86, year: 2017 },
  { name: 'Amber Heard', score: 91.85, year: 2016 },
  { name: 'Henry Cavill', score: 91.64, year: 2020 },
  { name: 'Kate Moss', score: 91.06, year: 2016 },
  { name: 'Scarlett Johansson', score: 90.91, year: 2019 },
  { name: 'Brad Pitt', score: 90.51, year: 2017 },
  { name: 'Marilyn Monroe', score: 89.41, year: 2016 },
  { name: 'Ryan Gosling', score: 87.48, year: 2020 },
];
