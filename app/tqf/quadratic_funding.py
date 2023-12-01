from io import BytesIO

import numpy as np
import pandas as pd
import panel as pn
import param as pm


class TunableQuadraticFunding(pm.Parameterized):

    donations_dashboard = pm.Selector(doc='Donations Dataset')
    boost_factory = pm.Selector()
    boosts = pm.DataFrame(precedence=-1)
    boost_coefficient = pm.Number(2, bounds=(0, 10), step=0.1)
    matching_pool = pm.Integer(25000, bounds=(0, 250_000), step=5_000)
    matching_percentage_cap = pm.Number(0.2, step=0.01, bounds=(0.01, 1))
    qf = pm.DataFrame(precedence=-1)
    boosted_donations = pm.DataFrame(precedence=-1)
    boosted_qf = pm.DataFrame(precedence=-1)
    results = pm.DataFrame(precedence=-1)
    mechanism = pm.Selector(
        default='Quadratic Funding',
        objects=[
            'Direct Donations',
            # '1p1v',
            'Quadratic Funding',
            # 'Pairwise Penalty',
            'Cluster Mapping',
        ],
    )

    @pm.depends('donations_dashboard', watch=True, on_init=True)
    def update_donations(self):
        self.donations = self.donations_dashboard.donations

    def _qf(
        self,
        donations_dataset,
        donation_column='amountUSD',
        mechanism='Quadratic Funding',
    ):
        # Group by 'Grant Name' and 'grantAddress', then apply calculations
        qf = donations_dataset.groupby(['Grant Name', 'grantAddress']).apply(
            lambda group: pd.Series(
                {
                    'Funding Mechanism': np.square(
                        np.sum(np.sqrt(group[donation_column]))
                    ),
                    'Direct Donations': group['amountUSD'].sum(),
                    'Boosted Donations': group[donation_column].sum(),
                }
            )
        )

        if mechanism == 'Direct Donations':
            qf['Funding Mechanism'] = 2 * qf['Boosted Donations']
        qf = qf.drop('Boosted Donations', axis=1)

        if mechanism == 'Cluster Mapping':
            qf['Funding Mechanism'] = self.donation_profile_clustermatch(
                donations_dataset,
                donation_column=donation_column,
            )

        # Sort values if needed
        qf = qf.sort_values(by='Funding Mechanism', ascending=False)

        # Calculate 'Matching Funding'
        qf['Matching Funding'] = qf['Funding Mechanism'] - qf['Direct Donations']

        # Calculate the stochastic vector funding distribution
        qf['Matching Distribution'] = (
            qf['Matching Funding'] / qf['Matching Funding'].sum()
        )

        # Applying a Cap to the Distribution
        qf['Matching Distribution'] = qf['Matching Distribution'].where(
            qf['Matching Distribution'] < self.matching_percentage_cap,
            self.matching_percentage_cap,
        )

        # Identify Mask of Distributions Less than the Cap
        mask = qf['Matching Distribution'] < self.matching_percentage_cap

        # Scale low distributions by 1 - sum of high distributions
        qf.loc[mask, 'Matching Distribution'] *= (
            1 - qf['Matching Distribution'][~mask].sum()
        ) / qf['Matching Distribution'][mask].sum()

        # Cap the high distributions
        qf['Matching Distribution'] = qf['Matching Distribution'].where(
            qf['Matching Distribution'] < self.matching_percentage_cap,
            self.matching_percentage_cap,
        )

        # Apply the Matching Pool
        qf['Matching Funds'] = qf['Matching Distribution'] * self.matching_pool

        # Apply the Matching Pool
        qf['Total Funding'] = qf['Matching Funds'] + qf['Direct Donations']

        return qf

    @pm.depends(
        'donations.param',
        'matching_pool',
        'matching_percentage_cap',
        'mechanism',
        watch=True,
        on_init=True,
    )
    def update_qf(self):
        self.qf = self._qf(self.donations.dataset, mechanism=self.mechanism)

    def view_qf_bar(self):
        return self.qf['quadratic_funding'].hvplot.bar(
            title='Quadratic Funding', shared_axes=False
        )

    def view_qf_distribution_bar(self):
        return self.qf['distribution'].hvplot.bar(
            title='Quadratic Funding Distribution', shared_axes=False
        )

    def view_qf_matching_bar(self):
        return self.qf['matching'].hvplot.bar(
            title='Quadratic Funding Distribution', shared_axes=False
        )

    @pm.depends('boost_factory.param', watch=True, on_init=True)
    def update_boosts(self):
        self.boosts = self.boost_factory.boost_outputs

    @pm.depends(
        'boosts',
        'boost_coefficient',
        'donations.dataset',
        watch=True,
        on_init=True,
    )
    def update_boosted_donations(self):
        # Merge Boosts into Donations
        boosted_donations = (
            self.donations.dataset.merge(
                self.boosts,
                how='left',
                left_on='voter',
                right_on='address',
            )
            .rename({'projectId_x': 'projectId'}, axis=1)
            .drop('projectId_y', axis=1)
        )

        # Non-boosted donations are initially set to 0
        print('Boosted Donations Nan')
        print(boosted_donations.isna().sum())
        boosted_donations = boosted_donations.fillna(0)

        # Set the Boost Coefficient
        boosted_donations['Boost Coefficient'] = (
            1 + self.boost_coefficient * boosted_donations['total_boost']
        )

        # Set the Boosted Amount as a Boost Coefficient * Donation Amount
        boosted_donations['Boosted Amount'] = (
            boosted_donations['Boost Coefficient'] * boosted_donations['amountUSD']
        )

        # Set the Boosted Donations on the TQF Class Instance
        self.boosted_donations = boosted_donations

    @pm.depends(
        'boosted_donations',
        'matching_pool',
        'matching_percentage_cap',
        'mechanism',
        watch=True,
        on_init=True,
    )
    def update_boosted_qf(self):
        print('Update Boosted QF')
        boosted_qf = self._qf(
            self.boosted_donations,
            donation_column='Boosted Amount',
            mechanism=self.mechanism,
        )
        print(boosted_qf['Total Funding'])
        self.boosted_qf = boosted_qf

    def donation_profile_clustermatch(self, donation_df, donation_column='amountUSD'):
        donation_df = donation_df.pivot_table(
            index='voter',
            columns=['Grant Name', 'grantAddress'],
            values=donation_column,
        ).fillna(0)
        # Convert donation dataframe to binary dataframe
        binary_df = (donation_df > 0).astype(int)

        # Create 'cluster' column representing the donation profile of each donor
        binary_df['cluster'] = binary_df.apply(
            lambda row: ''.join(row.astype(str)), axis=1
        )

        # Group by 'cluster' and sum donations from the same cluster
        cluster_sums = donation_df.groupby(binary_df['cluster']).sum()

        # Calculate the square root of each donation in the cluster
        cluster_sqrt = np.sqrt(cluster_sums)

        # Sum the square roots of all clusters grouped by project and square the sums
        funding = (cluster_sqrt.sum() ** 2).to_dict()

        return funding

    @pm.depends('boost_coefficient', watch=True, on_init=True)
    def project_stats(self, donation_column='Boosted Amount'):
        boosted_donations = self.boosted_donations
        projects = self.donations_dashboard.projects_table(
            donations_df=boosted_donations, donation_column=donation_column
        )
        sme_donations = boosted_donations[boosted_donations['address'] != 0]
        total_smes = sme_donations['address'].nunique()
        total_sme_donations = sme_donations[donation_column].sum()
        sme_stats = sme_donations.groupby('Grant Name').apply(
            lambda group: pd.Series(
                {
                    'Number of SMEs': group['address'].nunique(),
                    'Percentage of SMEs': group['address'].nunique() / total_smes,
                    'Total SME Donations': group[donation_column].sum(),
                    'Percent of Total SME Donations': group[donation_column].sum()
                    / total_sme_donations,
                    'Mean SME Donation': group[donation_column].mean(),
                    'Median SME Donation': group[donation_column].median(),
                    'Max SME Donations': group[donation_column].max(),
                    'Max SME Donor': group.loc[
                        group[donation_column].idxmax(), 'voter'
                    ],
                    'SMEs': [
                        a[:8] for a in sorted(group['address'].tolist(), reverse=True)
                    ],
                    'SME Donations': sorted(
                        group[donation_column].tolist(), reverse=True
                    ),
                }
            )
        )

        projects = projects.merge(
            sme_stats, how='outer', left_on='Grant Name', right_index=True
        )
        return projects

    @pm.depends('donations.dataset')
    def projects_table(self, donations_df, donation_column='amountUSD'):

        total_donations = donations_df[donation_column].sum()
        total_donors = donations_df['voter'].nunique()

        # Calculate Data per Project
        projects = (
            donations_df.groupby('Grant Name')
            .apply(
                lambda group: pd.Series(
                    {
                        'Number of Donors': group['voter'].nunique(),
                        'Percentage of Donors': group['voter'].nunique() / total_donors,
                        'Total Donations': group[donation_column].sum(),
                        'Percent of Total Donations': group[donation_column].sum()
                        / total_donations,
                        'Mean Donation': group[donation_column].mean(),
                        'Median Donation': group[donation_column].median(),
                        'Max Donations': group[donation_column].max(),
                        'Max Donor': group.loc[
                            group[donation_column].idxmax(), 'voter'
                        ],
                        'Donations': sorted(
                            group[donation_column].tolist(), reverse=True
                        ),
                    }
                )
            )
            .reset_index()
        )

        return projects

    @pm.depends('qf', 'boosted_qf', watch=True, on_init=True)
    def update_results(self):
        results = (
            self.project_stats()
            .drop(
                ['Max Donor', 'Donations', 'SMEs', 'SME Donations', 'Max SME Donor'],
                axis=1,
            )
            .merge(
                pd.merge(
                    self.qf,
                    self.boosted_qf,
                    on=['Grant Name', 'grantAddress'],
                    suffixes=('', ' Boosted'),
                ),
                on=['Grant Name'],
            )
        )
        # print(results)
        results['Matching Funds Boost Percentage'] = 100 * (
            (results['Matching Funds Boosted'] - results['Matching Funds'])
            / results['Matching Funds']
        ).round(4)
        results['Total Funding Boost Percentage'] = 100 * (
            (results['Total Funding Boosted'] - results['Total Funding'])
            / results['Total Funding']
        ).round(4)

        self.results = results
        return

    def get_results_csv(self):
        output = BytesIO()
        self.results.reset_index().to_csv(output, index=False)
        output.seek(0)
        return output

    def get_boosted_donations_csv(self):
        output = BytesIO()
        boosted_donations = self.boosted_donations
        boosted_donations[self.donations.dataset.columns].reset_index().to_csv(
            output, index=False
        )
        output.seek(0)
        return output

    def view_results(self):
        return self.results
        # return self.results.style.format(
        #     '{:.2f}',
        #     subset=pd.IndexSlice[
        #         :, self.results.select_dtypes(include=['float']).columns
        #     ],
        # )

    def view_results_bar(self):
        return self.results.sort_values(
            'Matching Funds Boost Percentage', ascending=False
        ).hvplot.bar(
            title='Matching Funds Boost Percentage',
            x='Grant Name',
            y='Matching Funds Boost Percentage',
            c='Matching Funds Boost Percentage',
            cmap='BrBG',
            ylim=(-100, 100),
            # clim=(-100, 100),
            colorbar=False,
            rot=65,
            height=1400,
            width=1200,
            fontscale=1.5,
            grid=True,
        )

    def view(self):
        boosted_donations_download = pn.widgets.FileDownload(
            callback=self.get_boosted_donations_csv,
            filename='boosted_donations.csv',
            button_type='primary',
        )
        results_download = pn.widgets.FileDownload(
            callback=self.get_results_csv,
            filename='results.csv',
            button_type='primary',
        )
        return pn.Column(
            self, self.view_results, boosted_donations_download, results_download
        )
