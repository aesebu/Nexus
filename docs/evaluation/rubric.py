# evaluation/rubric.py
from enum import IntEnum
class L(IntEnum):
    AWARENESS=1; UNDERSTANDING=2; PRACTITIONER=3; EXPERT=4; RESEARCHER=5

# format: domain: [(level, question, [keywords])]
RUBRIC = {
# ── A. วิทยาศาสตร์พื้นฐาน ──
"mathematics":       [(L.UNDERSTANDING,"อธิบาย linear algebra",["vector","matrix","eigen"]),(L.PRACTITIONER,"แก้ optimization",["gradient","convex"]),(L.EXPERT,"พิสูจน์ theorem",["proof","induction"])],
"physics":           [(L.UNDERSTANDING,"อธิบาย Newton vs relativity",["inertia","spacetime"]),(L.PRACTITIONER,"แก้โจทย์ thermodynamics",["entropy","heat"]),(L.EXPERT,"อธิบาย quantum entanglement",["superposition","nonlocal"])],
"chemistry":         [(L.UNDERSTANDING,"อธิบาย periodic table",["group","electron"]),(L.PRACTITIONER,"คำนวณ stoichiometry",["mole","balance"]),(L.EXPERT,"วิเคราะห์ reaction mechanism",["kinetics","catalyst"])],
"biology":           [(L.UNDERSTANDING,"อธิบาย DNA replication",["helix","polymerase"]),(L.PRACTITIONER,"วิเคราะห์ gene expression",["transcription","rna"]),(L.EXPERT,"อธิบาย CRISPR",["cas9","guide"])],
"astronomy":         [(L.UNDERSTANDING,"อธิบาย stellar evolution",["fusion","red giant"]),(L.PRACTITIONER,"คำนวณ orbital mechanics",["kepler","delta-v"]),(L.EXPERT,"วิเคราะห์ dark matter",["rotation","lensing"])],

# ── B. เทคโนโลยี ──
"cs":                [(L.UNDERSTANDING,"อธิบาย data structures",["array","tree","hash"]),(L.PRACTITIONER,"วิเคราะห์ complexity",["big-o","amortized"]),(L.EXPERT,"ออกแบบ distributed system",["consensus","cap"])],
"ai":                [(L.UNDERSTANDING,"อธิบาย RAG",["retrieval","vector","generation"]),(L.PRACTITIONER,"ออกแบบ multi-agent router",["routing","memory","orchestration"]),(L.EXPERT,"วิจารณ์ LLM alignment",["reward hacking","sycophancy"])],
"se":                [(L.UNDERSTANDING,"อธิบาย SDLC",["requirement","test","deploy"]),(L.PRACTITIONER,"ออกแบบ REST API",["rest","schema","versioning"]),(L.EXPERT,"วิเคราะห์ system design tradeoff",["latency","consistency","scale"])],
"robotics":          [(L.UNDERSTANDING,"อธิบาย kinematics",["joint","frame"]),(L.PRACTITIONER,"ออกแบบ PID control",["pid","feedback"]),(L.EXPERT,"วิเคราะห์ SLAM",["mapping","localization"])],
"cyber":             [(L.UNDERSTANDING,"อธิบาย MITRE ATT&CK",["tactic","technique"]),(L.PRACTITIONER,"วิเคราะห์ CVE chain",["cve","exploit","mitigation"]),(L.EXPERT,"ออกแบบ threat model",["stride","attack surface"])],

# ── C. ความคิดและมนุษย์ ──
"cogsci":            [(L.UNDERSTANDING,"อธิบาย working memory",["capacity","chunk"]),(L.PRACTITIONER,"วิเคราะห์ cognitive load",["intrinsic","extraneous"]),(L.EXPERT,"อธิบาย dual-process theory",["system1","system2"])],
"psych":             [(L.UNDERSTANDING,"อธิบาย classical conditioning",["stimulus","response"]),(L.PRACTITIONER,"วิเคราะห์ bias",["confirmation","anchoring"]),(L.EXPERT,"ออกแบบ experiment",["control","validity"])],
"neuro":             [(L.UNDERSTANDING,"อธิบาย neuron",["axon","synapse"]),(L.PRACTITIONER,"วิเคราะห์ fMRI data",["bold","activation"]),(L.EXPERT,"อธิบาย plasticity",["ltp","rewiring"])],
"phil":              [(L.UNDERSTANDING,"อธิบาย epistemology",["knowledge","justification"]),(L.PRACTITIONER,"วิเคราะห์ ethical dilemma",["utilitarian","deontological"]),(L.EXPERT,"วิเคราะห์ philosophy of mind",["qualia","functionalism"])],
"ling":              [(L.UNDERSTANDING,"อธิบาย syntax vs semantics",["grammar","meaning"]),(L.PRACTITIONER,"วิเคราะห์ phonology",["phoneme","allophone"]),(L.EXPERT,"อธิบาย universal grammar",["deep structure","innateness"])],

# ── D. สังคมและเศรษฐกิจ ──
"econ":              [(L.UNDERSTANDING,"อธิบาย supply-demand",["price","equilibrium"]),(L.PRACTITIONER,"วิเคราะห์ monetary policy",["interest","inflation"]),(L.EXPERT,"อธิบาย game theory equilibrium",["nash","payoff"])],
"biz":               [(L.UNDERSTANDING,"อธิบาย business model canvas",["value","revenue"]),(L.PRACTITIONER,"วิเคราะห์ SWOT",["strength","threat"]),(L.EXPERT,"ออกแบบ go-to-market",["segment","channel"])],
"soc":               [(L.UNDERSTANDING,"อธิบาย social structure",["norm","institution"]),(L.PRACTITIONER,"วิเคราะห์ inequality",["class","mobility"]),(L.EXPERT,"อธิบาย network theory",["tie","centrality"])],
"pol":               [(L.UNDERSTANDING,"อธิบาย separation of powers",["executive","judicial"]),(L.PRACTITIONER,"วิเคราะห์ voting system",["proportional","plurality"]),(L.EXPERT,"อธิบาย institutional design",["veto","coalition"])],
"law":               [(L.UNDERSTANDING,"อธิบาย rule of law",["statute","precedent"]),(L.PRACTITIONER,"วิเคราะห์ contract",["offer","consideration"]),(L.EXPERT,"อธิบาย jurisprudence",["positivism","natural law"])],

# ── E. วิศวกรรม ──
"eng":               [(L.UNDERSTANDING,"อธิบาย engineering design cycle",["requirement","prototype"]),(L.PRACTITIONER,"วิเคราะห์ structural load",["stress","strain"]),(L.EXPERT,"ออกแบบ safety factor",["failure mode","tolerance"])],
"arch":              [(L.UNDERSTANDING,"อธิบาย building code",["egress","fire"]),(L.PRACTITIONER,"วิเคราะห์ structural system",["beam","column"]),(L.EXPERT,"ออกแบบ sustainable building",["leed","passive"])],
"energy":            [(L.UNDERSTANDING,"อธิบาย renewable vs fossil",["solar","carbon"]),(L.PRACTITIONER,"วิเคราะห์ grid balancing",["load","storage"]),(L.EXPERT,"ออกแบบ energy system",["lcoe","dispatch"])],
"mfg":               [(L.UNDERSTANDING,"อธิบาย lean manufacturing",["waste","kanban"]),(L.PRACTITIONER,"วิเคราะห์ six sigma",["sigma","defect"]),(L.EXPERT,"ออกแบบ supply chain",["bullwhip","inventory"])],
"agri":              [(L.UNDERSTANDING,"อธิบาย crop rotation",["soil","nutrient"]),(L.PRACTITIONER,"วิเคราะห์ precision farming",["sensor","yield"]),(L.EXPERT,"อธิบาย food security",["supply","resilience"])],

# ── F. ความรู้และการปฏิบัติการ ──
"data":              [(L.UNDERSTANDING,"อธิบาย statistics",["mean","variance"]),(L.PRACTITIONER,"วิเคราะห์ regression",["feature","residual"]),(L.EXPERT,"ออกแบบ experiment",["randomization","power"])],
"research":          [(L.UNDERSTANDING,"อธิบาย scientific method",["hypothesis","test"]),(L.PRACTITIONER,"วิเคราะห์ literature review",["systematic","bias"]),(L.EXPERT,"ออกแบบ research design",["validity","replication"])],
"keng":              [(L.UNDERSTANDING,"อธิบาย ontology",["class","relation"]),(L.PRACTITIONER,"ออกแบบ knowledge graph",["entity","edge"]),(L.EXPERT,"อธิบาย taxonomy design",["hierarchy","facet"])],
"strat":             [(L.UNDERSTANDING,"อธิบาย SWOT vs Porter",["five forces","positioning"]),(L.PRACTITIONER,"วิเคราะห์ decision tree",["expected value","node"]),(L.EXPERT,"ออกแบบ strategy under uncertainty",["scenario","option"])],
"comm":              [(L.UNDERSTANDING,"อธิบาย communication model",["sender","receiver"]),(L.PRACTITIONER,"วิเคราะห์ persuasion",["ethos","pathos"]),(L.EXPERT,"ออกแบบ crisis communication",["stakeholder","message"])],

# ── G. 31–50 ส่วนขยาย ──
"history":           [(L.UNDERSTANDING,"อธิบาย historical method",["source","bias"]),(L.PRACTITIONER,"วิเคราะห์ primary source",["context","provenance"]),(L.EXPERT,"อธิบาย historiography",["narrative","revisionism"])],
"geo":               [(L.UNDERSTANDING,"อธิบาย geopolitics",["power","border"]),(L.PRACTITIONER,"วิเคราะห์ chokepoint",["strait","trade"]),(L.EXPERT,"อธิบาย heartland theory",["pivot","sphere"])],
"mil":               [(L.UNDERSTANDING,"อธิบาย principles of war",["mass","maneuver"]),(L.PRACTITIONER,"วิเคราะห์ force ratio",["combat power","logistics"]),(L.EXPERT,"อธิบาย deterrence",["credibility","escalation"])],
"intel":             [(L.UNDERSTANDING,"อธิบาย intelligence cycle",["collection","analysis"]),(L.PRACTITIONER,"วิเคราะห์ source reliability",["admiralty","corroboration"]),(L.EXPERT,"อธิบาย structured analytic technique",["ach","red team"])],
"crim":              [(L.UNDERSTANDING,"อธิบาย criminological theory",["strain","control"]),(L.PRACTITIONER,"วิเคราะห์ crime pattern",["hotspot","routine"]),(L.EXPERT,"อธิบาย restorative justice",["reintegration","victim"])],
"becon":             [(L.UNDERSTANDING,"อธิบาย prospect theory",["loss aversion","reference"]),(L.PRACTITIONER,"วิเคราะห์ nudge",["default","framing"]),(L.EXPERT,"อธิบาย bounded rationality",["satisficing","heuristic"])],
"anthro":            [(L.UNDERSTANDING,"อธิบาย ethnographic method",["participant","field"]),(L.PRACTITIONER,"วิเคราะห์ cultural relativism",["context","meaning"]),(L.EXPERT,"อธิบาย structural anthropology",["kinship","myth"])],
"edu":               [(L.UNDERSTANDING,"อธิบาย learning theory",["behaviorism","constructivism"]),(L.PRACTITIONER,"ออกแบบ curriculum",["objective","assessment"]),(L.EXPERT,"วิเคราะห์ pedagogy",["scaffolding","transfer"])],
"med":               [(L.UNDERSTANDING,"อธิบาย pathophysiology",["mechanism","symptom"]),(L.PRACTITIONER,"วิเคราะห์ diagnosis",["differential","test"]),(L.EXPERT,"อธิบาย evidence-based medicine",["rct","meta"])],
"pharm":             [(L.UNDERSTANDING,"อธิบาย pharmacokinetics",["absorption","half-life"]),(L.PRACTITIONER,"วิเคราะห์ drug interaction",["cyp450","contraindication"]),(L.EXPERT,"อธิบาย pharmacodynamics",["receptor","dose-response"])],
"eco":               [(L.UNDERSTANDING,"อธิบาย ecosystem",["food web","energy"]),(L.PRACTITIONER,"วิเคราะห์ climate feedback",["albedo","carbon"]),(L.EXPERT,"อธิบาย resilience theory",["tipping","adaptive"])],
"mat":               [(L.UNDERSTANDING,"อธิบาย crystal structure",["lattice","bond"]),(L.PRACTITIONER,"วิเคราะห์ material property",["stress","conductivity"]),(L.EXPERT,"อธิบาย metamaterial",["negative index","bandgap"])],
"trans":             [(L.UNDERSTANDING,"อธิบาย logistics",["supply","route"]),(L.PRACTITIONER,"วิเคราะห์ traffic flow",["queuing","capacity"]),(L.EXPERT,"ออกแบบ multimodal network",["intermodal","optimization"])],
"telecom":           [(L.UNDERSTANDING,"อธิบาย OSI layer",["protocol","packet"]),(L.PRACTITIONER,"วิเคราะห์ network latency",["bandwidth","jitter"]),(L.EXPERT,"อธิบาย 5G architecture",["slicing","mmwave"])],
"quantum":           [(L.UNDERSTANDING,"อธิบาย qubit",["superposition","entangle"]),(L.PRACTITIONER,"วิเคราะห์ quantum gate",["hadamard","cnot"]),(L.EXPERT,"อธิบาย error correction",["surface code","threshold"])],
"info":              [(L.UNDERSTANDING,"อธิบาย entropy",["shannon","bit"]),(L.PRACTITIONER,"วิเคราะห์ channel capacity",["snr","bandwidth"]),(L.EXPERT,"อธิบาย coding theory",["hamming","reed-solomon"])],
"art":               [(L.UNDERSTANDING,"อธิบาย art movement",["style","context"]),(L.PRACTITIONER,"วิเคราะห์ composition",["balance","contrast"]),(L.EXPERT,"อธิบาย aesthetics",["form","meaning"])],
"media":             [(L.UNDERSTANDING,"อธิบาย media ecology",["medium","message"]),(L.PRACTITIONER,"วิเคราะห์ framing",["agenda","narrative"]),(L.EXPERT,"อธิบาย platform economics",["attention","algorithm"])],
"rel":               [(L.UNDERSTANDING,"อธิบาย comparative religion",["ritual","belief"]),(L.PRACTITIONER,"วิเคราะห์ myth structure",["archetype","symbol"]),(L.EXPERT,"อธิบาย secularization",["modernity","pluralism"])],
"fut":               [(L.UNDERSTANDING,"อธิบาย foresight",["trend","scenario"]),(L.PRACTITIONER,"วิเคราะห์ delphi method",["expert","consensus"]),(L.EXPERT,"ออกแบบ scenario planning",["driver","uncertainty"])],
}

def load_into(evaluator_rubric: dict):
    """merge เข้ากับ RUBRIC เดิมของ harness"""
    for k, items in RUBRIC.items():
        evaluator_rubric.setdefault(k, []).extend(
            [{"q": q, "kw": kw, "level": lv} for lv, q, kw in items]
        )
    return len(evaluator_rubric)
