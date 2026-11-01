from app.services.job_sections import extract_sections
from app.services.ollama_analysis import needs_assessment


def test_needs_assessment_infrastructure():
    passage = {'text': "Very good knowledge of the on-premises infrastructure based on Windows Server technologies (Active Directory, File Server, Certificate Services etc.)", 'hints': []}
    assert needs_assessment(passage) is True

def test_needs_assessment_virtualization():
    passage = {'text': "Strong background in configuration and management of min. one virtualization platform (VMware, Hyper-V, Proxmox)", 'hints': []}
    assert needs_assessment(passage) is True

def test_needs_assessment_german_skills():
    passage = {'text': "German language skills", 'hints': []}
    assert needs_assessment(passage) is True

def test_needs_assessment_english_fluency():
    passage = {'text': "This role requires collaboration with customers from all around the world, therefore fluency in English is required (minimum B2 level). German language will be a huge plus.", 'hints': []}
    assert needs_assessment(passage) is True

def test_extract_sections_mandatory_expertise():
    text = """Required technical and professional expertise:
    Knowledge of Azure public cloud"""
    units, _ = extract_sections(text)
    # The first line is a heading, the second line is the content.
    # extract_sections logic for "Required technical and professional expertise:"
    # results in category 'mandatory' for the next line.
    assert units[0].category == "mandatory"
    assert "Knowledge of Azure public cloud" in units[0].quote

def test_extract_sections_responsibility():
    text = """At cloudatus, you will:
    Administer and maintain on-premises and cloud-based infrastructure environments"""
    units, _ = extract_sections(text)
    # For "At cloudatus, you will:", it might be a heading.
    # "Administer and maintain..." should be category 'responsibility' because of DUTY regex.
    assert units[0].category == "responsibility"
    assert "Administer and maintain" in units[0].quote
