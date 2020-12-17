import io
import zipfile
from typing import Optional, List
from functools import reduce

import requests
import us
import pandas as pd

import tabula

import logging

from can_tools.scrapers.base import CMU, DatasetBase
from can_tools.scrapers.official.base import StateDashboard

logger = logging.getLogger(__name__)


class Kentucky(DatasetBase, StateDashboard):
    start_date = "2020-12-17"
    # source = (
    #     "https://www.mass.gov/info-details/"
    #     "covid-19-response-reporting#covid-19-daily-dashboard-"
    # )
    state_fips = int(us.states.lookup("Kentucky").fips)
    has_location = True
    location_type = "county"

    def fetch(self):
        """

        :return:
        """
        file = "https://chfs.ky.gov/agencies/dph/covid19/COVID19DailyReport.pdf"
        tables: List[pd.DataFrame] = tabula.read_pdf(file, pages="all", multiple_tables=True)

        dfs = []
        start = False
        for df in tables:

            if start:
                if (df.iloc[:, 0] == "Total").any():
                    start = False

                dfs.append(df)

            elif {"County", "New Cases"}.issubset(set(df.columns)):
                dfs.append(df)
                start = True
            else:
                pass

        def reducer(left_df: pd.DataFrame, right_df: pd.DataFrame) -> pd.DataFrame:
            if {"County", "New Cases"}.issubset(set(left_df.columns)):
                if {"County", "New Cases"}.issubset(set(right_df.columns)):
                    return pd.concat([left_df, right_df], ignore_index=True)
                else:
                    return pd.concat(
                        (
                            left_df,
                            right_df.T.reset_index().T.rename(
                                columns={0: "County", 1: "New Cases", 2: "Percent"}
                            ).reset_index(drop=True)
                        ), ignore_index=True
                    )
            else:
                if {"County", "New Cases"}.issubset(set(right_df.columns)):
                    return pd.concat(
                        (
                            right_df,
                            left_df.T.reset_index().T.rename(
                                columns={0: "County", 1: "New Cases", 2: "Percent"}
                            ).reset_index(drop=True)
                        ), ignore_index=True
                    )
                else:
                    return pd.concat(
                        (
                            right_df,
                            left_df
                        ), ignore_index=True
                    ).T.reset_index().T.rename(
                        columns={0: "County", 1: "New Cases", 2: "Percent"}
                    ).reset_index(drop=True)

        df = reduce(lambda left, right: reducer(left, right), dfs)

        df["last_updated"] = self.execution_dt

        return df

    def _fetch(self):
        """

        :return:
        """
        data = self.fetch()
        success = self._store_clean(data)

        return success

    def normalize(self, data: pd.DataFrame) -> pd.DataFrame:
        """

        :param data:
        :return:
        """
        # TODO The location must be transformed to the FIPS Code

        data_df = data.rename(columns={
            "County": "location",
            "New Cases": "value"
        })

        # us.states.lookup("Kentucky").

        data_df['vintage'] = self._retrieve_vintage()
        data_df['sex'] = 'all'
        data_df['gender'] = 'all'
        data_df['race'] = 'all'
        data_df['measurement'] = 'new'
        data_df['unit'] = 'people'
        data_df['category'] = 'cases'

        # this forces numeric values
        data_df["value"] = pd.to_numeric(data_df["value"])

        cols_to_keep = [
            "vintage",
            "dt",
            "location",
            "category",
            "measurement",
            "unit",
            "age",
            "race",
            "sex",
            "value",
        ]

        return data_df[cols_to_keep]

    def _normalize(self):
        """

        :return:
        """
        # Ingest the data
        data: pd.DataFrame = self._read_clean()

        # Clean data using `_normalize`
        df = self.normalize(data)
        success = self._store_clean(df)

        return success
