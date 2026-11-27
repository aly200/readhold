from readhold.density import score
from readhold.terms import find_acronyms, find_definitions
from readhold.text import looks_like_heading, section_kind, split_sentences


def test_split_protects_abbreviations_and_decimals():
    s = split_sentences("Smith et al. showed this in Fig. 3. The accuracy was 93.5% on test. J. Doe disagreed! Why? Because e.g. the data was small.")
    assert s == [
        "Smith et al. showed this in Fig. 3.",
        "The accuracy was 93.5% on test.",
        "J. Doe disagreed!",
        "Why?",
        "Because e.g. the data was small.",
    ]


def test_split_handles_quotes_and_dehyphenation():
    s = split_sentences('He said "it works." Then it broke. The exam-\nple was fine.')
    assert s == ['He said "it works."', "Then it broke.", "The example was fine."]


def test_split_empty():
    assert split_sentences("   ") == []


def test_section_kinds():
    assert section_kind("Abstract") == "abstract"
    assert section_kind("1 Introduction") == "intro"
    assert section_kind("2. Related Work") == "related"
    assert section_kind("3 Our Approach") == "method"
    assert section_kind("4.1 Experimental Results") == "results"
    assert section_kind("References") == "references"
    assert section_kind("6 Conclusion and Future Work") == "conclusion"
    assert section_kind("A Note on Cats") == "other"


def test_heading_detection():
    assert looks_like_heading("1. Introduction")
    assert looks_like_heading("RELATED WORK")
    assert not looks_like_heading("This is a normal sentence that ends with a period.")


def test_density_orders_easy_below_dense():
    easy = score("The cat sat on the mat and looked at the dog.")
    dense = score("We minimize the KL divergence D_KL(p||q) = Σ p log p/q over 1.2M tokens using AdamW with β2=0.95.")
    jargon = score("Heteroscedastic variational autoencoders marginalize latent posteriors.")
    assert 0 <= easy < 0.2
    assert dense > 0.5
    assert jargon > easy + 0.3
    assert score("") == 0


def test_acronyms():
    found = find_acronyms([
        "We use Long Short-Term Memory (LSTM) and Reinforcement Learning from Human Feedback (RLHF).",
        "A convolutional neural network (CNN) is used. The results (RES) of nothing.",
    ])
    assert found["LSTM"] == "Long Short-Term Memory"
    assert found["RLHF"] == "Reinforcement Learning from Human Feedback"
    assert found["CNN"] == "convolutional neural network"
    assert "RES" not in found


def test_definition_finder_prefers_defining_sentence():
    sents = [
        (0, "The router appears in many systems."),
        (1, "We define a router as a module that picks which tokens attend."),
        (2, "A router is a small network."),
    ]
    hits = find_definitions("router", sents)
    assert hits[0]["sentence"] == 1
    assert {h["sentence"] for h in hits} >= {1, 2}


def test_definition_finder_falls_back_to_first_use():
    hits = find_definitions("router", [(4, "Nothing here."), (5, "The router was slow.")])
    assert hits == [{"sentence": 5, "text": "The router was slow.", "pattern": "first use", "score": 0.1}]


def test_definition_finder_symbols():
    assert find_definitions("C++", [(0, "C++ is a language with templates.")])[0]["sentence"] == 0
