import hvplot.pandas  # noqa
import panel as pn
import param as pm

from .boost import Boost
from .boost_factory import BoostFactory
from .dataset import TEGR1_TEA, TEGR1_TEC, Donations
from .donations_dashboard import DonationsDashboard
from .outcomes import Outcomes
from .quadratic_funding import TunableQuadraticFunding

pn.extension('tabulator')

# TEGR1

tegr1_donations = Donations(
    name='TEGR1 Donations', file='./app/input/vote_coefficients_input.csv'
)

# Select which round to load donations for
tegr1_donations_dashboard = DonationsDashboard(donations=tegr1_donations)

tegr1_tec_distribution = TEGR1_TEC(name='TEC Token')
tegr1_tea_distribution = TEGR1_TEA(name='TEA Credentials')


tegr1_tec_boost = Boost(
    name='TEGR1 TEC Boost',
    input=tegr1_tec_distribution,
    transformation='Threshold',
    threshold=10,
    token_logy=True,
)

tegr1_tea_boost = Boost(
    name='TEGR1 TEA Boost',
    input=tegr1_tea_distribution,
    transformation='Threshold',
    threshold=1,
)


tegr1_boost_factory = BoostFactory(
    name='TEGR1 Boost Factory', boost_template=tegr1_tec_boost
)
tegr1_boost_factory.param['boost_template'].objects = [tegr1_tec_boost, tegr1_tea_boost]
tegr1_boost_factory._new_boost()
tegr1_boost_factory.boost_template = tegr1_tea_boost
tegr1_boost_factory._new_boost()

tegr1_qf = TunableQuadraticFunding(
    donations=tegr1_donations, boost_factory=tegr1_boost_factory
)

outcomes = Outcomes(
    donations_dashboard=tegr1_donations_dashboard,
    boost_factory=tegr1_boost_factory,
    tqf=tegr1_qf,
)

tegr1_app = pn.Tabs(
    ('Donations', pn.Column(tegr1_donations.view(), tegr1_donations_dashboard.view())),
    (
        'Token Distribution',
        pn.Row(tegr1_tec_distribution.view, tegr1_tec_distribution.view_distribution),
    ),
    (
        'TEA Token Distribution',
        pn.Row(tegr1_tea_distribution.view, tegr1_tea_distribution.view_distribution),
    ),
    # ('Boost Tuning', tegr1_tec_boost.view()),
    ('Boost Factory', tegr1_boost_factory.view()),
    ('Tunable Quadradic Funding', tegr1_qf.view()),
    ('Outcomes', outcomes.view()),
    active=5,
    dynamic=True,
)
