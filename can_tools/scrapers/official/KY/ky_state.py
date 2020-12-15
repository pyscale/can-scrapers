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
    start_date = "2019-04-29"
    source = (
        "https://www.mass.gov/info-details/"
        "covid-19-response-reporting#covid-19-daily-dashboard-"
    )
    state_fips = int(us.states.lookup("Kentucky").fips)
    has_location = False

    def transform_date(self, date: pd.Timestamp) -> pd.Timestamp:
        return date - pd.Timedelta(hours=11)

    def _get_cases_deaths(self, zf: zipfile.ZipFile) -> pd.DataFrame:
        with zf.open("County.csv") as csv_f:
            df = pd.read_csv(csv_f, parse_dates=["Date"])

        names = {"Date": "dt", "County": "county"}
        cats = {
            "Total Confirmed Cases": CMU(
                category="cases", measurement="cumulative", unit="people"
            ),
            "Total Probable and Confirmed Deaths": CMU(
                category="deaths", measurement="cumulative", unit="people"
            ),
        }
        out = df.rename(columns=names).loc[:, list(names.values()) + list(cats.keys())]
        melted = out.melt(id_vars=["dt", "county"], value_vars=list(cats.keys()))

        return (
            melted.drop_duplicates(subset=["dt", "county", "variable"], keep="first")
            .pipe(self.extract_CMU, cats)
            .drop(["variable"], axis=1)
            .assign(value=lambda x: x["value"].fillna(-1).astype(int))
        )

    def _get_hospital_data(
        self, zf: zipfile.ZipFile, date: pd.Timestamp
    ) -> Optional[pd.DataFrame]:
        fn = "HospCensusBedAvailable.xlsx"
        if fn not in [x.filename for x in zf.filelist]:
            print("The file HospCensusBedAvailable.xlsx could not be found, skipping")
            return None
        with zf.open(fn, "r") as f:
            # NOTE: needed b/c python 3.6 doesn't have `.seek` method on
            # zipfile objects and pandas expects it
            content = io.BytesIO(f.read())
            df = pd.read_excel(content, sheet_name="Hospital COVID Census")

        hosp_col = [x for x in list(df) if "Including ICU" in x]
        if len(hosp_col) != 1:
            raise ValueError(
                f"Could not find total hospital column from list: {list(df)}"
            )

        icu_col = [x for x in list(df) if "ICU Census" in x]
        if len(icu_col) != 1:
            raise ValueError(f"Could not find ICU column from list: {list(df)}")

        cats = {
            hosp_col[-1]: CMU(
                category="hospital_beds_in_use_covid",
                measurement="current",
                unit="beds",
            ),
            icu_col[-1]: CMU(
                category="icu_beds_in_use_covid", measurement="current", unit="beds"
            ),
        }

        return (
            df.groupby("Hospital County")[list(cats.keys())]
            .sum()
            .reset_index()
            .rename(columns={"Hospital County": "county"})
            .assign(dt=date)
            .melt(id_vars=["dt", "county"])
            .pipe(self.extract_CMU, cats)
            .drop(["variable"], axis=1)
        )

    def get(self, date: str) -> pd.DataFrame:

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

        dt = pd.to_datetime(date)

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

        df["last_updated"] = dt

        df["value"] = df["value"].astype(int)
        df["vintage"] = self._retrieve_vintage()
        return df
