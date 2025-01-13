from typing import List, Optional
from pathlib import Path
import json
from datetime import datetime
import logging
import sys
from locust import HttpUser, task, constant, events
import asyncio
from asyncio import create_subprocess_exec, gather
from asyncio.subprocess import PIPE

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
locust_logger = logging.getLogger('locust_output')
locust_logger.setLevel(logging.INFO)

class WebsiteUser(HttpUser):
    wait_time = constant(0)

    def on_start(self):
        self.target_url = self.environment.host
        
    @task
    def test_endpoint(self):
        self.client.get(self.target_url)

@events.quitting.add_listener
def save_results(environment, **kwargs):
    """Save test results to JSON file"""
    stats = []
    for stat in environment.stats.entries.values():
        stats.append({
            "endpoint": stat.name,
            "method": stat.method,
            "requests": stat.num_requests,
            "failures": stat.num_failures,
            "median_response_time": stat.median_response_time,
            "average_response_time": stat.avg_response_time,
            "min_response_time": stat.min_response_time,
            "max_response_time": stat.max_response_time,
        })

    report = {
        "target_url": environment.host,
        "total_requests": environment.stats.total.num_requests,
        "total_failures": environment.stats.total.num_failures,
        "average_response_time": environment.stats.total.avg_response_time,
        "median_response_time": environment.stats.total.median_response_time,
        "min_response_time": environment.stats.total.min_response_time,
        "max_response_time": environment.stats.total.max_response_time,
        "stats": stats,
        "timestamp": datetime.now().isoformat(),
        "test_duration": getattr(environment.stats.total, 'last_request_timestamp', 0) - 
                        getattr(environment.stats.total, 'start_time', 0)
    }

    results_dir = Path("performance_tests/break_check")
    results_dir.mkdir(parents=True, exist_ok=True)

    url_part = environment.host.replace('https://', '').replace('http://', '').replace('/', '_').replace('.', '_')
    filename = results_dir / f"{url_part}.json"
    
    with open(filename, "w") as f:
        json.dump(report, f, indent=4)
    logger.info(f"Test results saved to {filename}")

class LoadTestRunner:
    """Manages execution of load tests for URLs"""
    
    def __init__(self, base_dir: str = "performance_tests"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def _run_single_test(self, url: str, users: int, spawn_rate: int, run_time: str) -> None:
        """Run a load test for a single URL"""
        cmd = [
            sys.executable,
            '-m', 'locust',
            '-f', __file__,
            '--headless',
            '-u', str(users),
            '-r', str(spawn_rate),
            '--run-time', run_time,
            '--only-summary',
            '--host', url
        ]

        try:
            process = await create_subprocess_exec(
                *cmd,
                stdout=PIPE,
                stderr=PIPE
            )

            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                text = line.decode().strip()
                if text:
                    logger.info(f"[{url}] {text}")

            await process.wait()
            
        except Exception as e:
            logger.error(f"Error testing {url}: {e}")
        finally:
            if process and process.returncode is None:
                process.terminate()
                await process.wait()

    async def run_concurrent_tests(self, urls: List[str], users: int = 1000, 
                                 spawn_rate: int = 1000, run_time: str = "30") -> None:
        """Run load tests for multiple URLs concurrently"""
        unique_urls = list(dict.fromkeys(urls))
        logger.info(f"Starting concurrent tests for {len(unique_urls)} URLs")
        
        tasks = [
            self._run_single_test(url, users, spawn_rate, run_time)
            for url in unique_urls
        ]
        await gather(*tasks)

def run_break_test(urls: List[str], run_time: Optional[int] = 30):
    """Main entry point for running load tests"""
    if not urls:
        logger.error("No URLs provided")
        return

    run_time_str = str(run_time)
    runner = LoadTestRunner()
    
    try:
        asyncio.run(runner.run_concurrent_tests(
            urls=urls,
            users=1000,
            spawn_rate=1000,
            run_time=run_time_str
        ))
        logger.info("Load tests completed successfully")
    except KeyboardInterrupt:
        logger.info("Tests interrupted by user")
    except Exception as e:
        logger.error(f"Tests failed with error: {e}")

# if __name__ == "__main__":
#     test_urls = [
#         "https://example.com",
#         "https://anotherexample.com"
#     ]
#     run_load_tests(test_urls)