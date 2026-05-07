import logging

logger = logging.getLogger(__name__)

def run_evaluation_batch_job():
    logger.info("Running nightly autonomous evaluation...")
    from .autonomous_evaluator import run_evaluation_batch
    try:
        run_evaluation_batch()
        logger.info("Nightly autonomous evaluation complete.")
    except Exception as e:
        logger.error(f"Nightly evaluation failed: {e}")
