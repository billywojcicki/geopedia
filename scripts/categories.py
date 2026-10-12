"""Category rules: Wikidata root classes -> map category / weighting.

Each of an item's P31 classes is walked up the P279 (subclass of) graph and
matched to its *nearest* root below. The item takes the role with the smallest
distance; ties go to the role listed first in ROLE_PRIORITY. Nearest-match
matters: Wikidata's class tree is messy (protests are, eventually, a
"conflict"; Paris is, eventually, an "electoral unit").
"""

# Display categories (index = category id used in the data files).
CATEGORIES = ["conflict", "politics", "disaster", "culture", "science", "built", "people"]

ROOTS = {
    "conflict": [
        "Q178561",  # battle
        "Q188055",  # siege
        "Q198",  # war
        "Q645883",  # military operation
        "Q831663",  # military campaign
        "Q180684",  # conflict
        "Q13427116",  # peasant revolt (otherwise a riot, one step closer)
        "Q1323212",  # insurgency
        "Q350604",  # armed conflict
        "Q124734",  # rebellion
        "Q3199915",  # massacre
        "Q2223653",  # terrorist attack
        "Q45382",  # coup d'etat
        "Q1361229",  # conquest
        "Q467011",  # invasion
        "Q2380335",  # airstrike
        "Q678146",  # bombardment
        "Q188686",  # military occupation
        "Q135010",  # war crime
        "Q750215",  # mass murder
        "Q891854",  # bomb attack
        "Q41397",  # genocide
        "Q623179",  # state terrorism
    ],
    "politics": [
        "Q131569",  # treaty
        "Q273120",  # protest
        "Q124757",  # riot
        "Q10931",  # revolution
        "Q3882219",  # assassination
        "Q1072326",  # summit
        "Q49776",  # strike
        "Q625994",  # convention
        "Q111161",  # synod
        "Q29102902",  # papal election
        "Q40231",  # public election
        "Q132821",  # murder
        "Q16738832",  # criminal case
        "Q2761147",  # meeting
        "Q209715",  # coronation
        "Q2627975",  # ceremony
        "Q900406",  # reform
        "Q1262732",  # purge
        "Q934744",  # political scandal
        "Q518554",  # partition
        "Q25929224",  # transfer of sovereignty
        "Q1140229",  # political union
        "Q1064441",  # democratization
        "Q546113",  # public policy
        "Q49773",  # social movement
        "Q2738074",  # political movement
        "Q6056746",  # campaign
        "Q1020018",  # stock market crash
        "Q290178",  # economic crisis
        "Q176494",  # recession
        "Q207781",  # economic bubble
    ],
    "disaster": [
        "Q3839081",  # disaster
        "Q8065",  # natural disaster
        "Q7944",  # earthquake
        "Q744913",  # aviation accident
        "Q1078765",  # railway accident
        "Q168983",  # conflagration
        "Q8068",  # flood
        "Q3241045",  # disease outbreak
        "Q179057",  # explosion
        "Q169950",  # wildfire
        "Q8081",  # tornado
        "Q1550225",  # mining accident
        "Q852190",  # shipwreck
        "Q7692360",  # volcanic eruption
        "Q8092",  # tropical cyclone
        "Q168247",  # famine
        "Q171558",  # accident
    ],
    "culture": [
        "Q132241",  # festival
        "Q464980",  # exhibition
        "Q172754",  # world's fair
        "Q182832",  # concert
        "Q465299",  # archaeological culture
        "Q968159",  # art movement
        "Q238526",  # golden age
    ],
    "science": [
        "Q2401485",  # expedition
        "Q101965",  # experiment
        "Q12772819",  # discovery
        "Q2133344",  # space mission
        "Q5916",  # spaceflight
        "Q797476",  # rocket launch
        "Q210112",  # nuclear weapons testing
    ],
    # Sports are culture, but only kept when very notable (Olympics, World Cups).
    # Other yearly editions (pageants, festivals, contests) get the same bar.
    "sports": [
        "Q16510064",  # sporting event
        "Q3001412",  # horse race
        "Q27020041",  # sports season (World Cups live here)
        "Q476300",  # competition
        "Q27968055",  # recurring event edition
    ],
    # Never shown: noise for a history map, or coordinates that mean nothing.
    "exclude": [
        "Q4504495",  # award ceremony
        "Q1060829",  # broadcaster
        "Q1573906",  # concert tour
        "Q3887",  # solar eclipse
        "Q220397",  # saros (eclipse series)
        "Q14350",  # radio station
        "Q1616075",  # television station
        "Q27971968",  # constituency of the House of Commons
        "Q6256",  # country (modern countries sit at meaningless centroids)
        "Q3624078",  # sovereign state
        "Q18524218",  # canton of France
        "Q45400320",  # open-access publisher
        "Q13406463",  # Wikimedia list article
        "Q4167836",  # Wikimedia category
        "Q5398426",  # television series
        "Q11424",  # film
        "Q1555508",  # radio program
        "Q7187",  # gene
        "Q148578",  # space telescope
        "Q34770",  # language
        "Q618779",  # award
        "Q41710",  # ethnic group
        "Q9174",  # religion
        "Q3305213",  # painting (sits wherever the museum is)
        "Q93184",  # drawing
        "Q11060274",  # print
        "Q125191",  # photograph
        "Q87167",  # manuscript
        "Q7725634",  # literary work
        "Q8142",  # currency
        "Q11032",  # newspaper
        "Q41298",  # magazine
        "Q1792644",  # art style
        "Q7397",  # software
        "Q220659",  # archaeological artifact (comes in as a discovery instead)
    ],
    # Kept, but heavily down-weighted (mundane for a history map).
    "low": [
        "Q12819564",  # station (rail, metro, tram)
        "Q3914",  # school
        "Q4830453",  # business
        "Q783794",  # company
        "Q163740",  # nonprofit organization
        "Q847017",  # sports club
        "Q327333",  # government agency
        "Q11315",  # shopping center
        "Q11707",  # restaurant
        "Q41253",  # movie theater
        "Q34442",  # road
        "Q28575",  # county (bot-made articles inflate their sitelinks)
        "Q47168",  # county of the United States
        "Q56061",  # administrative territorial entity (cities match "settlement" first)
        "Q82794",  # geographic region
    ],
}

# Place roles: all shown as "built" on the map, but they pick the verb
# ("Built" / "Founded" / "Established") and keep items from being excluded.
ROOTS["structure"] = ["Q811979", "Q41176", "Q839954"]  # built structure, building, archaeological site
ROOTS["settlement"] = [
    "Q486972",  # human settlement
    "Q515",  # city (listed directly: it is also, more distantly, an admin unit)
    "Q3957",  # town
    "Q532",  # village
    "Q5119",  # capital
    "Q3024240",  # historical country
    "Q133311",  # tribe
]
ROOTS["institution"] = [
    "Q3918",  # university
    "Q33506",  # museum
    "Q7075",  # library
    "Q16917",  # hospital
    "Q2385804",  # educational institution
    "Q43229",  # organization (fallback, usually far away)
]

# Politics comes after culture and science: its roots (meeting, ceremony) are
# broad, so on a tie the more specific reading wins (a film festival is a
# meeting too).
EVENT_ROLES = ["conflict", "disaster", "science", "culture", "politics", "sports"]
PLACE_ROLES = ["settlement", "structure", "institution", "low"]
ROLE_PRIORITY = EVENT_ROLES + PLACE_ROLES + ["exclude"]
