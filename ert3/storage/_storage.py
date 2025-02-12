import json
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Set
import io
import logging
import pandas as pd
from pydantic import BaseModel
import requests
import ert3

from ert_shared.storage.connection import get_info

logger = logging.getLogger(__name__)

_STORAGE_TOKEN = None
_STORAGE_URL = None
_ENSEMBLE_RECORDS = "__ensemble_records__"
_SPECIAL_KEYS = (_ENSEMBLE_RECORDS,)


class _NumericalMetaData(BaseModel):
    class Config:
        validate_all = True
        validate_assignment = True
        extra = "forbid"
        allow_mutation = False
        arbitrary_types_allowed = True

    ensemble_size: int
    record_type: ert3.data.RecordType


def _assert_server_info() -> None:
    global _STORAGE_URL, _STORAGE_TOKEN  # pylint: disable=global-statement

    if _STORAGE_URL is None:
        info = get_info()
        _STORAGE_URL = info["baseurl"]
        _STORAGE_TOKEN = info["auth"][1]


def _get_from_server(
    path: str,
    headers: Optional[Dict[Any, Any]] = None,
    status_code: int = 200,
    **kwargs: Any,
) -> requests.Response:

    _assert_server_info()
    if not headers:
        headers = {}
    headers["Token"] = _STORAGE_TOKEN

    resp = requests.get(url=f"{_STORAGE_URL}/{path}", headers=headers, **kwargs)
    if resp.status_code != status_code:
        logger.error("Failed to fetch from %s. Response: %s", path, resp.text)

    return resp


def _delete_on_server(
    path: str, headers: Optional[Dict[Any, Any]] = None, status_code: int = 200
) -> requests.Response:

    _assert_server_info()
    if not headers:
        headers = {}
    headers["Token"] = _STORAGE_TOKEN
    resp = requests.delete(
        url=f"{_STORAGE_URL}/{path}",
        headers=headers,
    )
    if resp.status_code != status_code:
        logger.error("Failed to delete %s. Response: %s", path, resp.text)

    return resp


def _post_to_server(
    path: str,
    headers: Optional[Dict[Any, Any]] = None,
    status_code: int = 200,
    **kwargs: Any,
) -> requests.Response:

    _assert_server_info()
    if not headers:
        headers = {}
    headers["Token"] = _STORAGE_TOKEN
    resp = requests.post(url=f"{_STORAGE_URL}/{path}", headers=headers, **kwargs)
    if resp.status_code != status_code:
        logger.error("Failed to post to %s. Response: %s", path, resp.text)

    return resp


def _put_to_server(
    path: str,
    headers: Optional[Dict[Any, Any]] = None,
    status_code: int = 200,
    **kwargs: Any,
) -> requests.Response:

    _assert_server_info()
    if not headers:
        headers = {}
    headers["Token"] = _STORAGE_TOKEN
    resp = requests.put(url=f"{_STORAGE_URL}/{path}", headers=headers, **kwargs)
    if resp.status_code != status_code:
        logger.error("Failed to put to %s. Response: %s", path, resp.text)

    return resp


def _get_experiment_by_name(experiment_name: str) -> Dict[str, Any]:
    response = _get_from_server(path="experiments")
    if response.status_code != 200:
        raise ert3.exceptions.StorageError(response.text)
    experiments = {exp["name"]: exp for exp in response.json()}
    return experiments.get(experiment_name, None)


def init(*, workspace: Path) -> None:
    response = _get_from_server(path="experiments")
    experiment_names = {exp["name"]: exp["ensemble_ids"] for exp in response.json()}

    for special_key in _SPECIAL_KEYS:
        if f"{workspace}.{special_key}" in experiment_names:
            raise ValueError("Storage already initialized")
        _init_experiment(
            workspace=workspace,
            experiment_name=f"{workspace}.{special_key}",
            parameters=[],
            ensemble_size=-1,
        )


def init_experiment(
    *,
    workspace: Path,
    experiment_name: str,
    parameters: Iterable[str],
    ensemble_size: int,
) -> None:
    if ensemble_size <= 0:
        raise ValueError("Ensemble cannot have a size <= 0")

    _init_experiment(
        workspace=workspace,
        experiment_name=experiment_name,
        parameters=parameters,
        ensemble_size=ensemble_size,
    )


def _init_experiment(
    *,
    workspace: Path,
    experiment_name: str,
    parameters: Iterable[str],
    ensemble_size: int,
) -> None:
    if not experiment_name:
        raise ValueError("Cannot initialize experiment without a name")

    if _get_experiment_by_name(experiment_name) is not None:
        raise ert3.exceptions.ElementExistsError(
            f"Cannot initialize existing experiment: {experiment_name}"
        )

    exp_response = _post_to_server(path="experiments", json={"name": experiment_name})
    exp_id = exp_response.json()["id"]
    response = _post_to_server(
        path=f"experiments/{exp_id}/ensembles",
        json={
            "parameter_names": list(parameters),
            "response_names": [],
            "size": ensemble_size,
        },
    )
    if response.status_code != 200:
        raise ert3.exceptions.StorageError(response.text)


def get_experiment_names(*, workspace: Path) -> Set[str]:
    response = response = _get_from_server(path="experiments")
    experiment_names = {exp["name"] for exp in response.json()}
    for special_key in _SPECIAL_KEYS:
        key = f"{workspace}.{special_key}"
        if key in experiment_names:
            experiment_names.remove(key)
    return experiment_names


def _get_record_type(ensemble_record: ert3.data.EnsembleRecord) -> ert3.data.RecordType:
    record_type = ensemble_record.records[0].record_type
    for record in ensemble_record.records:
        if record.record_type != record_type:
            raise ValueError("Inconsistent record type")

    return record_type


def _add_numerical_data(
    workspace: Path,
    experiment_name: str,
    record_name: str,
    ensemble_record: ert3.data.EnsembleRecord,
) -> None:
    experiment = _get_experiment_by_name(experiment_name)
    if experiment is None:
        raise ert3.exceptions.NonExistantExperiment(
            f"Cannot add {record_name} data to "
            f"non-existing experiment: {experiment_name}"
        )

    metadata = _NumericalMetaData(
        ensemble_size=ensemble_record.ensemble_size,
        record_type=_get_record_type(ensemble_record),
    )

    ensemble_id = experiment["ensemble_ids"][0]  # currently just one ens per exp
    record_url = f"ensembles/{ensemble_id}/records/{record_name}"

    for idx, record in enumerate(ensemble_record.records):
        df = pd.DataFrame([record.data], columns=record.index, index=[idx])
        response = _post_to_server(
            path=f"{record_url}/matrix",
            params={"realization_index": idx},
            data=df.to_csv().encode(),
            headers={"content-type": "text/csv"},
        )

        if response.status_code == 409:
            raise ert3.exceptions.ElementExistsError("Record already exists")

        if response.status_code != 200:
            raise ert3.exceptions.StorageError(response.text)

        meta_response = _put_to_server(
            path=f"{record_url}/userdata",
            params={"realization_index": idx},
            json=metadata.dict(),
        )

        if meta_response.status_code != 200:
            raise ert3.exceptions.StorageError(meta_response.text)


def _response2record(
    response_content: bytes, record_type: ert3.data.RecordType, realization_id: int
) -> ert3.data.Record:
    dataframe = pd.read_csv(
        io.BytesIO(response_content), index_col=0, float_precision="round_trip"
    )

    raw_index = tuple(dataframe.columns)
    if record_type == ert3.data.RecordType.LIST_FLOAT:
        array_data = tuple(
            float(dataframe.loc[realization_id][raw_idx]) for raw_idx in raw_index
        )
        return ert3.data.Record(data=array_data)
    elif record_type == ert3.data.RecordType.MAPPING_INT_FLOAT:
        int_index = tuple(int(e) for e in dataframe.columns)
        idata = {
            idx: float(dataframe.loc[realization_id][raw_idx])
            for raw_idx, idx in zip(raw_index, int_index)
        }
        return ert3.data.Record(data=idata)
    elif record_type == ert3.data.RecordType.MAPPING_STR_FLOAT:
        str_index = tuple(str(e) for e in dataframe.columns)
        sdata = {
            idx: float(dataframe.loc[realization_id][raw_idx])
            for raw_idx, idx in zip(raw_index, str_index)
        }
        return ert3.data.Record(data=sdata)
    else:
        raise ValueError(
            f"Unexpected record type when loading numerical record: {record_type}"
        )


def _get_numerical_metadata(ensemble_id: str, record_name: str) -> _NumericalMetaData:
    response = _get_from_server(
        path=f"ensembles/{ensemble_id}/records/{record_name}/userdata",
        params={"realization_index": 0},  # This assumes there is a realization 0
    )

    if response.status_code == 404:
        raise ert3.exceptions.ElementMissingError(
            f"No metadata for {record_name} in ensemble: {ensemble_id}"
        )

    if response.status_code != 200:
        raise ert3.exceptions.StorageError(response.text)

    return _NumericalMetaData(**json.loads(response.content))


def _get_numerical_data(
    workspace: Path, experiment_name: str, record_name: str
) -> ert3.data.EnsembleRecord:
    experiment = _get_experiment_by_name(experiment_name)
    if experiment is None:
        raise ert3.exceptions.NonExistantExperiment(
            f"Cannot get {record_name} data, no experiment named: {experiment_name}"
        )

    ensemble_id = experiment["ensemble_ids"][0]  # currently just one ens per exp
    metadata = _get_numerical_metadata(ensemble_id, record_name)

    records = []
    for real_id in range(metadata.ensemble_size):
        response = _get_from_server(
            path=f"ensembles/{ensemble_id}/records/{record_name}",
            params={"realization_index": real_id},
            headers={"accept": "text/csv"},
        )

        if response.status_code == 404:
            raise ert3.exceptions.ElementMissingError(
                f"No {record_name} data for experiment: {experiment_name}"
            )

        if response.status_code != 200:
            raise ert3.exceptions.StorageError(response.text)

        record = _response2record(
            response.content,
            metadata.record_type,
            real_id,
        )
        records.append(record)

    return ert3.data.EnsembleRecord(records=records)


def add_ensemble_record(
    *,
    workspace: Path,
    record_name: str,
    ensemble_record: ert3.data.EnsembleRecord,
    experiment_name: Optional[str] = None,
) -> None:
    if experiment_name is None:
        experiment_name = f"{workspace}.{_ENSEMBLE_RECORDS}"

    _add_numerical_data(workspace, experiment_name, record_name, ensemble_record)


def get_ensemble_record(
    *,
    workspace: Path,
    record_name: str,
    experiment_name: Optional[str] = None,
) -> ert3.data.EnsembleRecord:
    if experiment_name is None:
        experiment_name = f"{workspace}.{_ENSEMBLE_RECORDS}"

    return _get_numerical_data(workspace, experiment_name, record_name)


def get_ensemble_record_names(
    *, workspace: Path, experiment_name: Optional[str] = None
) -> Iterable[str]:
    if experiment_name is None:
        experiment_name = f"{workspace}.{_ENSEMBLE_RECORDS}"
    experiment = _get_experiment_by_name(experiment_name)
    if experiment is None:
        raise ert3.exceptions.NonExistantExperiment(
            f"Cannot get record names of non-existing experiment: {experiment_name}"
        )

    ensemble_id = experiment["ensemble_ids"][0]  # currently just one ens per exp
    response = _get_from_server(path=f"ensembles/{ensemble_id}/records")
    if response.status_code != 200:
        raise ert3.exceptions.StorageError(response.text)
    return list(response.json().keys())


def get_experiment_parameters(
    *, workspace: Path, experiment_name: str
) -> Iterable[str]:

    experiment = _get_experiment_by_name(experiment_name)
    if experiment is None:
        raise ert3.exceptions.NonExistantExperiment(
            f"Cannot get parameters from non-existing experiment: {experiment_name}"
        )

    ensemble_id = experiment["ensemble_ids"][0]  # currently just one ens per exp
    response = _get_from_server(path=f"ensembles/{ensemble_id}/parameters")
    if response.status_code != 200:
        raise ert3.exceptions.StorageError(response.text)
    return list(response.json())


def delete_experiment(*, workspace: Path, experiment_name: str) -> None:

    experiment = _get_experiment_by_name(experiment_name)
    if experiment is None:
        raise ert3.exceptions.NonExistantExperiment(
            f"Experiment does not exist: {experiment_name}"
        )
    response = _delete_on_server(path=f"experiments/{experiment['id']}")

    if response.status_code != 200:
        raise ert3.exceptions.StorageError(response.text)
