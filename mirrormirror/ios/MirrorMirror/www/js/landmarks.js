/* MediaPipe Face Landmarker index map (478 points: 468 mesh + 10 iris).
   Naming follows MediaPipe: LEFT means the subject's own left, which appears on the
   image's RIGHT in an unmirrored camera frame. Anthropometric names follow Farkas. */

export const LM = {
  // Midline, top to bottom
  FOREHEAD_TOP: 10,     // top of the face oval. The mesh has no hairline point; this is the upper forehead (approximate trichion).
  GLABELLA: 9,          // between the eyebrows
  NASION: 168,          // bridge of the nose, between the inner eye corners (sellion)
  NOSE_TIP: 1,          // pronasale
  SUBNASALE: 2,         // base of the columella, where the nose meets the upper lip
  LABRALE_SUP: 0,       // top edge of the upper lip (cupid's bow centre)
  STOMION_UPPER: 13,    // inner edge of the upper lip (lip contact line)
  STOMION_LOWER: 14,    // inner edge of the lower lip
  LABRALE_INF: 17,      // bottom edge of the lower lip
  SULCUS: 18,           // mentolabial sulcus (chin crease)
  POGONION: 199,        // soft tissue chin point
  MENTON: 152,          // bottom of the chin

  // Face width
  ZYGION_R: 234, ZYGION_L: 454,   // widest points of the face oval, in front of the ears
  GONION_R: 172, GONION_L: 397,   // jaw angles

  // Eyes (R = subject's right = image left in an unmirrored frame)
  EXOCANTHION_R: 33,  ENDOCANTHION_R: 133,  // outer and inner corners, right eye
  EXOCANTHION_L: 263, ENDOCANTHION_L: 362,  // outer and inner corners, left eye
  EYE_TOP_R: 159, EYE_BOTTOM_R: 145,
  EYE_TOP_L: 386, EYE_BOTTOM_L: 374,
  IRIS_R: 468, IRIS_L: 473,               // iris centres
  IRIS_R_RING: [469, 470, 471, 472], IRIS_L_RING: [474, 475, 476, 477],

  // Eyebrows
  BROW_INNER_R: 107, BROW_PEAK_R: 105, BROW_OUTER_R: 70,
  BROW_INNER_L: 336, BROW_PEAK_L: 334, BROW_OUTER_L: 300,

  // Nose width (alar base)
  ALAR_R: 129, ALAR_L: 358,
  ALAR_OUTER_R: 48, ALAR_OUTER_L: 278,

  // Mouth
  CHEILION_R: 61, CHEILION_L: 291,       // mouth corners

  // Cheeks (for symmetry)
  CHEEK_R: 50, CHEEK_L: 280,
};

/** Midline landmarks used to fit the facial axis for the symmetry measurement. */
export const MIDLINE = [10, 151, 9, 8, 168, 6, 197, 195, 5, 4, 1, 19, 94, 2, 164, 0, 13, 14, 17, 18, 200, 199, 175, 152];

/** Bilateral pairs [right, left, label] used for the symmetry measurement. */
export const PAIRS = [
  [33, 263, 'outer eye corner'],
  [133, 362, 'inner eye corner'],
  [468, 473, 'pupil'],
  [159, 386, 'upper eyelid'],
  [145, 374, 'lower eyelid'],
  [70, 300, 'eyebrow tail'],
  [105, 334, 'eyebrow arch'],
  [107, 336, 'eyebrow head'],
  [129, 358, 'nostril'],
  [61, 291, 'mouth corner'],
  [234, 454, 'cheekbone'],
  [172, 397, 'jaw angle'],
  [50, 280, 'cheek'],
];

/** Sparse outline used for the live preview (a light, pretty subset of the mesh). */
export const PREVIEW_POINTS = [
  10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109, // oval
  33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246, // right eye
  263, 249, 390, 373, 374, 380, 381, 382, 362, 398, 384, 385, 386, 387, 388, 466, // left eye
  61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185, // outer lips
  70, 63, 105, 66, 107, 336, 296, 334, 293, 300, // brows
  168, 6, 197, 195, 5, 4, 1, 2, 98, 327, 129, 358, 48, 278, // nose
  468, 473, 9, 199,
];
