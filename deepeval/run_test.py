"""Function for running test
"""
import os
from typing import List, Optional, Union
from dataclasses import dataclass
from .retry import retry
from .client import Client
from .constants import IMPLEMENTATION_ID_ENV, LOG_TO_SERVER_ENV
from .get_api_key import _get_api_key, _get_implementation_name
from .metrics import Metric
from .test_case import LLMTestCase


def _is_api_key_set():
    result = _get_api_key()
    # if result == "" or result is None:
    #     warnings.warn(
    #         """API key is not set - you won't be able to log to the DeepEval dashboard. Please set it by running `deepeval login`"""
    #     )
    if result == "" or result is None:
        return False
    return True


def _is_send_okay():
    # DOing this until the API endpoint is fixed
    return _is_api_key_set() and os.getenv(LOG_TO_SERVER_ENV) != "Y"


def _get_init_values(metric: Metric):
    # We use this method for sending useful metadata
    init_values = {
        param: getattr(metric, param)
        for param in vars(metric)
        if isinstance(getattr(metric, param), (str, int, float))
    }
    return init_values


def _send_to_server(
    self,
    success: bool,
    metric_score: float,
    metric_name: str,
    query: str = "-",
    output: str = "-",
    expected_output: str = "-",
    metadata: Optional[dict] = None,
    context: str = "-",
    **kwargs,
):
    if _is_send_okay():
        api_key = _get_api_key()
        client = Client(api_key=api_key)
        implementation_name = _get_implementation_name()
        # implementation_id = os.getenv(IMPLEMENTATION_ID_ENV, "")
        # if implementation_id != "":
        implementation_id = client.get_implementation_id_by_name(
            implementation_name
        )
        os.environ[IMPLEMENTATION_ID_ENV] = implementation_id
        datapoint_id = client.add_golden(
            query=query, expected_output=expected_output, context=context
        )

        metric_metadata: dict = _get_init_values()
        if metadata:
            metric_metadata.update(metadata)

        return client.add_test_case(
            metric_score=float(metric_score),
            metric_name=metric_name,
            actual_output=output,
            query=query,
            implementation_id=implementation_id,
            metrics_metadata=metric_metadata,
            success=bool(success),
            datapoint_id=datapoint_id["id"],
        )


def log(
    success: bool = True,
    score: float = 1e-10,
    metric_name: str = "-",
    query: str = "-",
    output: str = "-",
    expected_output: str = "-",
    metadata: Optional[dict] = None,
    context: str = "-",
):
    """Log to the server.

    Parameters
    - query: What was asked to the model. This can also be context.
    - output: The LLM output.
    - expected_output: The output that's expected.
    """
    if _is_send_okay():
        _send_to_server(
            metric_score=score,
            metric_name=metric_name,
            query=query,
            output=output,
            expected_output=expected_output,
            success=success,
            metadata=metadata,
            context=context,
        )


@dataclass
class TestResult:
    """Returned from run_test"""

    success: bool
    score: float
    metric_name: str
    query: str
    output: str
    expected_output: str
    metadata: Optional[dict]
    context: str

    def __gt__(self, other: "TestResult") -> bool:
        """Greater than comparison based on score"""
        return self.score > other.score

    def __lt__(self, other: "TestResult") -> bool:
        """Less than comparison based on score"""
        return self.score < other.score


def run_test(
    test_cases: Union[LLMTestCase, List[LLMTestCase]],
    metrics: List[Metric],
    raise_error: bool = False,
    max_retries: int = 1,
    delay: int = 1,
    min_success: int = 1,
) -> List[TestResult]:
    """
    Args:
        test_cases: Either a single test case or a list of test cases to run
        metrics: List of metrics to run
        raise_error: Whether to raise an error if a metric fails
        max_retries: Maximum number of retries for each metric measurement
        delay: Delay in seconds between retries
        min_success: Minimum number of successful measurements required

    Example:
        >>> from deepeval.metrics.facutal_consistency import FactualConsistencyMetric
        >>> from deepeval.test_case import LLMTestCase
        >>> from deepeval.run_test import run_test
        >>> metric = FactualConsistencyMetric()
        >>> test_case = LLMTestCase(
        ...     query="What is the capital of France?",
        ...     output="Paris",
        ...     expected_output="Paris",
        ...     context="Geography",
        ... )
        >>> run_test(test_case, metric)
    """
    if isinstance(test_cases, LLMTestCase):
        test_cases = [test_cases]

    test_results = []
    for test_case in test_cases:
        for metric in metrics:

            @retry(
                max_retries=max_retries, delay=delay, min_success=min_success
            )
            def measure_metric():
                score = metric.measure(test_case)
                success = metric.is_successful()
                log(
                    success=success,
                    score=score,
                    metric_name=metric.__name__,
                    query=test_case.query if test_case.query else "-",
                    output=test_case.output if test_case.output else "-",
                    expected_output=test_case.expected_output
                    if test_case.expected_output
                    else "-",
                    context=test_case.context,
                )
                test_result = TestResult(
                    success=success,
                    score=score,
                    metric_name=metric.__name__,
                    query=test_case.query if test_case.query else "-",
                    output=test_case.output if test_case.output else "-",
                    expected_output=test_case.expected_output
                    if test_case.expected_output
                    else "-",
                    metadata=None,
                    context=test_case.context,
                )
                test_results.append(test_result)

                if raise_error:
                    assert (
                        metric.is_successful()
                    ), f"{metric.__name__} failed. Score: {score}."

            measure_metric()

    return test_results


def assert_test(
    test_cases: Union[LLMTestCase, List[LLMTestCase]],
    metrics: List[Metric],
    raise_error: bool = False,
    max_retries: int = 1,
    delay: int = 1,
    min_success: int = 1,
) -> List[TestResult]:
    """Assert a test"""
    return run_test(
        test_cases=test_cases,
        metrics=metrics,
        raise_error=raise_error,
        max_retries=max_retries,
        delay=delay,
        min_success=min_success,
    )