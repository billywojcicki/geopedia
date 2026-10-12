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
        "Q21480300",  # mass shooting (not a disaster)
        "Q1520311",  # violent crime (Wikidata files it under "disaster")
        "Q1933595",  # hijacking
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
    "Q217327",  # suicide attack (otherwise a "suicide": a disaster)
    "Q676324",  # armada (the Spanish Armada; otherwise an organization)
    ],
    "politics": [
        "Q131569",  # treaty
        "Q273120",  # protest
    "Q175331",  # demonstration (otherwise an "organization")
    "Q88178910",  # assassination attempt (otherwise a violent crime)
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
        "Q2334719",  # legal case (Wikidata files it under "conflict")
        "Q59532",  # christianization (of a people or state)
        "Q820655",  # statute (the Enabling Act, Constitutio Antoniniana)
        "Q7748",  # law
        "Q1156854",  # policy (Glasnost)
        "Q1127126",  # military alliance
        "Q100906234",  # multinational military coalition (the Triple Entente)
        "Q3771738",  # instrument of surrender
        "Q192909",  # scandal (Wikidata files these under "conflict")
        "Q1255828",  # controversy
        "Q1123131",  # disputation
        "Q179875",  # debate
        "Q8016240",  # trial
    "Q2282872", "Q669970",  # diet, Imperial Diet (the Diet of Worms; otherwise an organization)
    "Q93288",  # contract (the Treaty of Waitangi)
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
        "Q3002150",  # aircraft crash
        "Q81054",  # storm
        "Q828827",  # power outage
    ],
    "culture": [
        "Q188976",  # counterculture
        "Q132241",  # festival
        "Q464980",  # exhibition
        "Q172754",  # world's fair
        "Q182832",  # concert
        "Q465299",  # archaeological culture
        "Q968159",  # art movement
        "Q238526",  # golden age
    "Q8432",  # civilization (the Zapotecs; otherwise just a "group of humans")
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
        "Q1573906",  # concert tour
        "Q3887",  # solar eclipse
        "Q24706",  # Japanese era name (calendar periods, not events)
        "Q16022392",  # edit-a-thon
        "Q79786",  # Wikimedia meetup
        "Q26132862",  # Olympic sports discipline event (the Games themselves stay)
        "Q3010369",  # opening ceremony
        "Q1156329",  # auto show
        "Q1129398",  # fan convention
        "Q548126",  # anime convention
        "Q1958056",  # science fiction convention
        "Q152450",  # municipal election
        "Q15280243",  # mayoral election
        "Q1057954",  # by-election
        "Q6508670",  # leadership election
        "Q3464665",  # television series season
        "Q21191270",  # television series episode
        "Q220397",  # saros (eclipse series)
    "Q482994",  # album
    "Q1384330", "Q176799",  # expeditionary force, military unit (the Afrika Korps is not an expedition)
        "Q14350",  # radio station
        "Q1616075",  # television station
        "Q27971968",  # constituency of the House of Commons
        "Q6256",  # country (modern countries sit at meaningless centroids)
        "Q3624078",  # sovereign state
        "Q18524218",  # canton of France
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
        "Q1076486",  # sports venue (stadiums; the Colosseum is an archaeological site first)
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
ROLE_PRIORITY = EVENT_ROLES + PLACE_ROLES + ["exclude", "exclude-weak"]

# Weak exclusions: only when nothing else claims the item (Stanford is a
# university and an open-access publisher; the Royal Albert Hall a concert hall
# and a broadcaster).
ROOTS["exclude-weak"] = [
    "Q45400320",  # open-access publisher
    "Q1060829",  # broadcaster
    "Q9174",  # religion
    "Q1445650", "Q57598", "Q18574943",  # holiday, national day, annual commemoration (the Battle of Preveza is Turkish Navy Day)
]

# Dated items none of the roots claim are kept as events (and shown under
# Politics), unless they are one of these: things, not things that happened.
NOT_EVENTS = [
    "Q17376908",  # languoid (languages, language families)
    "Q15617994",  # administrative territorial entity type (Counties of Sweden)
    "Q28872924",  # designation for an administrative territorial entity
    "Q12737077", "Q528892", "Q28640", "Q16335296",  # occupation, profession
    "Q4164871", "Q294414", "Q4189293",  # position, public office, title
    "Q196600",  # media franchise (not "creative work": speeches and declarations are ones)
    "Q15142894", "Q42314054", "Q3231690", "Q59773381",  # weapon, ammunition, automobile models
    "Q6545185", "Q694554",  # unique identifier, emergency telephone number
    "Q16334295", "Q17197366",  # group of humans, type of organization
    "Q174984", "Q2095", "Q7239",  # signal, food, organism (not "product": speeches reach it)
    "Q645466", "Q110055303", "Q59152282", "Q477544",  # national emblem, rocket model, streaming service, new religious movement
]

# Famous moments the denylist above would catch (the Wow! signal is a signal,
# RDS-1 and the Tsar Bomba bombs, the Radium Girls a group of people), with
# their category.
KEEP_EVENTS = {"Q33297": "science", "Q586755": "science", "Q188596": "science", "Q1128589": "politics"}
