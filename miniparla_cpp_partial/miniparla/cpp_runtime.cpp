#include "cpp_runtime.hpp"

#include <vector>
#include <mutex>
#include <thread>
#include <iostream>
#include <string>
#include <chrono>

//Input: PythonTask
//Explaination: Call python routine to attempt to grab a worker thread, assign a task to it, and then notify the thread. 
//Output: If no worker thread is available, return false. Otherwise, return true.
void launch_task_callback(callerfunc func, void* f, void* arg) {
    //std::cout << "launch_task_callback" << std::endl;
    func(f, arg);
    //std::cout << "launch_task_callback done" << std::endl;
    return;
}

void launch_stop_callback(stopfunc func, void* f) {
    ////std::cout << "launch_stop_callback" << std::endl;
    return func(f);
}

//InnerTask Class Methods

InnerTask::InnerTask() {
    this->id = 0;
    this->task = NULL;
    this->vcus = 0.0;

    this->dependencies = std::vector<InnerTask*>();
    this->num_deps = 0;
    this->dependents = std::vector<InnerTask*>();
}

InnerTask::InnerTask(long id, void* task, float vcus) {
    this->id = id;
    this->task = task;
    this->vcus = vcus;

    this->dependencies = std::vector<InnerTask*>();
    this->dependents = std::vector<InnerTask*>();

    this->num_deps = 0;
}

void InnerTask::set_task(void* task) {
    this->task = task;
}

void InnerTask::add_dependency_unsafe(InnerTask* task) {
    if (task->add_dependent(this)){
        ////std::cout << "Adding dependency " << task->id << std::endl;
        this->dependencies.push_back(task);
        this->num_deps++;
    }
    ////std::cout << "Num deps: " << this->num_deps << std::endl;
}

void InnerTask::add_dependency(InnerTask* task) {
    this->m.lock();
    //std::cout << "add_dependency (c++) " << this->num_deps << std::endl;
    this->add_dependency_unsafe(task);
    this->m.unlock();
}

void InnerTask::add_dependencies(std::vector<InnerTask*> task_list){
    this->m.lock();
    for (int i = 0; i < task_list.size(); i++) {
        this->add_dependency_unsafe(task_list[i]);
    }
    this->m.unlock();
}

void InnerTask::clear_dependencies(){
    this->m.lock();
    this->dependencies.clear();
    this->m.unlock();
}  

bool InnerTask::blocked(){
    this->m.lock();
    bool blocked = this->dependencies.size() > 0;
    this->m.unlock();
    return blocked;
}

int InnerTask::get_num_deps(){
    this->m.lock();
    int num_deps = this->num_deps;
    this->m.unlock();
    return num_deps;
}

bool InnerTask::blocked_unsafe(){
    return this->dependencies.size() > 0;
}

bool InnerTask::add_dependent(InnerTask* task){
    this->m.lock();
    if (this->complete){
        //std::cout << "Task " << this->id << " is already complete" << std::endl;
        this->m.unlock();
        return false;
    }
    else{
        this->dependents.push_back(task);
        //std::cout << "Task " << this->id << " is NOT COMPLETE" << std::endl;
        this->m.unlock();
        return true;
    }
}

void InnerTask::notify_dependents(InnerScheduler* scheduler){
    this->m.lock();
    //std::cout << "notify_dependents " << this->id << std::endl;
    this->complete = true;
    for (int i = 0; i < this->dependents.size(); i++) {
        bool notify = this->dependents[i]->notify();
        //std::cout << "notify_status " << notify << std::endl;
        if (notify) {
            //std::cout << "Enqueueing task" << std::endl;
            scheduler->enqueue_task(this->dependents[i]);
        }
    }
    this->m.unlock();
}

bool InnerTask::notify(){
    //std::cout << "Task is being notified" << this->num_deps << std::endl;
    this->m.lock();
    int deps = --this->num_deps;
    this->m.unlock();
    bool condition = (deps == 0);
    //std::cout << "Task has been notified" << condition << std::endl;
    return condition;
}

//InnerScheduler Class Methods

InnerScheduler::InnerScheduler() {
    this->func = NULL;
    this->resources = 1;
    this->active_tasks = 1;
    this->running_tasks = 0;

    this->ready_queue = std::vector<InnerTask*>();

    this->free_threads = 1;
}

InnerScheduler::InnerScheduler(callerfunc call, float resources, int nthreads) {
    this->call = call;
    this->resources = resources;
    this->active_tasks = 1;
    this->running_tasks = 0;

    this->ready_queue = std::vector<InnerTask*>();
    this->free_threads = 0;
}

void InnerScheduler::set_python_callback(callerfunc call, stopfunc py_stop, void* f) {
    ////std::cout << "set_python_callback" << std::endl;
    this->func = f;
    this->call = call;
    this->py_stop = py_stop;
}

void InnerScheduler::set_resources(float resources) {
    this->resources_mutex.lock();
    this->resources = resources;
    this->resources_mutex.unlock();
}

void InnerScheduler::set_nthreads(int nthreads) {
    this->free_threads_mutex.lock();
    this->free_threads = nthreads;
    this->free_threads_mutex.unlock();
}

//Enqueue a task to ready (Safe/Unsafe)
void InnerScheduler::enqueue_task(InnerTask* task){
    this->ready_queue_mutex.lock();
    this->ready_queue.push_back(task);
    this->ready_queue_mutex.unlock();
}

void InnerScheduler::enqueue_task_unsafe(InnerTask* task){
    this->ready_queue.push_back(task);
}

//Dequeue a task from ready (Safe/Unsafe)
InnerTask* InnerScheduler::dequeue_task(){
    this->ready_queue_mutex.lock();
    InnerTask* task = this->ready_queue.back();
    this->ready_queue.pop_back();
    this->ready_queue_mutex.unlock();
    return task;
}

InnerTask* InnerScheduler::dequeue_task_unsafe(){
    InnerTask* task = this->ready_queue.back();
    this->ready_queue.pop_back();
    return task;
}

int InnerScheduler::get_ready_queue_size(){
    this->ready_queue_mutex.lock();
    int size = this->ready_queue.size();
    this->ready_queue_mutex.unlock();
    return size;
}

int InnerScheduler::get_ready_queue_size_unsafe(){
    return this->ready_queue.size();
}

//Launch Tasks Task Callback
bool InnerScheduler::run_launcher(){

    ////std::cout << "run_launcher" << std::endl;

    if (this->launching_phase_mutex.try_lock() ) {
        //Only run the launcher if there are free threads and there are tasks to run
        bool condition = this->get_free_threads() > 0 && this->get_active_tasks() != 0;

        ////std::cout << "launcher condition " << condition << std::endl;

        if(condition){
            ////std::cout << "Number of free threads: " << this->get_free_threads() << std::endl;
            ////std::cout << "Launching Phase (Get Ready Queue Lock)" << std::endl;
            this->ready_queue_mutex.lock();
            //std::cout << "Launching Phase (Has Ready Queue Lock)" << std::endl;
            //Grab a task from the ready queue
            bool has_task = this->get_ready_queue_size_unsafe() > 0;
            //std::cout << "Has Task: " << has_task << std::endl;
            if(has_task){
                InnerTask* task = this->dequeue_task_unsafe();
                //std::cout << "Dequeue Task" << std::endl;
                this->ready_queue_mutex.unlock();

                //std::cout << "Task: " << task->id << std::endl;

                //Launch the task
                this->launch_task(task);

                //std::cout << "Launched Task." << std::endl;

                //Release the lock
                this->launching_phase_mutex.unlock();
                return true;
            }
            else{
                //std::cout << "No more tasks" << std::endl;
                this->ready_queue_mutex.unlock();
                this->launching_phase_mutex.unlock();
                return false;
            }
        }
        this->launching_phase_mutex.unlock();
    }

    return false;
}

void InnerScheduler::run_scheduler(){
    //std::cout << "Running Scheduler Callback" << std::endl;
    bool launch_succeed = this->run_launcher();
    //while(this->get_running_tasks() == 0 and this->get_active_tasks() > 1){
    //   launch_succeed = this->run_launcher();
    //}
    //std::cout << "Scheduler Callback Finished: " << this->active_tasks << std::endl;
}

//Launch Task python callback
void InnerScheduler::launch_task(InnerTask* task){

    //this->resources_mutex.lock();
    //std::cout << "Launcher:: Has resource lock" << std::endl;
    ////std::cout << "Launching Task (Internal)" << std::endl;
    //Get Python task
    void* py_task = task->task;

    //std::cout << "Resources: " << this->get_resources_unsafe() << " " << task->vcus << std::endl;

    if(this->get_resources_unsafe() - task->vcus < 0){
        //std::cout << "Not enough resources. Re-enqueing." << std::endl;
        //this->resources_mutex.unlock();
        this->enqueue_task_unsafe(task);
        return;
    }

    //std::cout << "Launching Task (Internal) 2" << std::endl;

    //Call python routine to attempt to grab a worker thread, assign a task to it, and then notify the thread.
    //If no worker thread is available, return false. Otherwise, return true.
    launch_task_callback(this->call, this->func, py_task);

    //std::cout << "Launching Task (Internal) 3" << std::endl;

    bool success = true;

    //If successful, increment running tasks
    //If not successful, re-enqueue task
    if( success) {
        this->incr_running_tasks();
        this->decr_free_threads();
        //std::cout << "Decrementing free threads" << this->get_free_threads_unsafe() << std::endl;

        this->decr_resources_unsafe(task->vcus);
    }
    else {
        this->enqueue_task_unsafe(task);
    }
    //this->resources_mutex.unlock();
    //std::cout << "Launcher:: Released resource lock" << std::endl;
}

void InnerScheduler::run(){
    //while (this->should_run) {
        //run scheduler phases
        //this->run_scheduler();
        //sleep
        //std::this_thread::sleep_for(std::chrono::milliseconds(1));

    //}
}

//Stop
void InnerScheduler::stop(){
    //std::cout << "Stopping Scheduler" << std::endl;
    this->should_run = false;
    launch_stop_callback(this->py_stop, this->func);
}

//Incr/Decr Counters

//running tasks
void InnerScheduler::incr_running_tasks(){
    this->running_tasks++;
}

void InnerScheduler::decr_running_tasks(){
    this->running_tasks--;
}

//active tasks
void InnerScheduler::incr_active_tasks(){
    this->active_tasks_mutex.lock();
    this->active_tasks++;
    this->active_tasks_mutex.unlock();
}

bool InnerScheduler::decr_active_tasks(){

    this->active_tasks_mutex.lock();
    this->active_tasks--;
    bool condition = this->active_tasks == 0;
    this->active_tasks_mutex.unlock();

    if (condition){
        this->stop();
    }

    return condition;
}

//threads 
void InnerScheduler::incr_free_threads(){
    this->free_threads++;
}

void InnerScheduler::decr_free_threads(){
    this->free_threads--;
}

//resources
void InnerScheduler::incr_resources(float resources){
    ////std::cout<<"Incrementing resources: try to get lock"<< std::endl;
    //this->resources_mutex.lock();
    ////std::cout<<"Incrementing resources: got lock"<< std::endl;
    //this->resources += resources;
    this->resources.fetch_add(resources, std::memory_order_relaxed);
    //this->resources_mutex.unlock();
    ////std::cout<<"Incrementing resources: released lock"<< std::endl;

}

void InnerScheduler::incr_resources_unsafe(float resources){
    //this->resources += resources;
    this->resources.fetch_add(resources, std::memory_order_relaxed);
}

void InnerScheduler::decr_resources(float resources){
    //this->resources_mutex.lock();
    //this->resources -= resources;
    this->resources.fetch_sub(resources, std::memory_order_relaxed);
    //this->resources_mutex.unlock();
}

void InnerScheduler::decr_resources_unsafe(float resources){
    //this->resources -= resources;
    this->resources.fetch_sub(resources, std::memory_order_relaxed);
}

//Get Counters
int InnerScheduler::get_running_tasks(){
    int running_tasks = this->running_tasks;
    return running_tasks;
}

int InnerScheduler::get_running_tasks_unsafe(){
    return this->running_tasks;
}

int InnerScheduler::get_active_tasks(){
    this->active_tasks_mutex.lock();
    int active_tasks = this->active_tasks;
    this->active_tasks_mutex.unlock();
    return active_tasks;
}

int InnerScheduler::get_active_tasks_unsafe(){
    return this->active_tasks;
}

int InnerScheduler::get_free_threads(){
    int free_threads = this->free_threads;
    return free_threads;
}

int InnerScheduler::get_free_threads_unsafe(){
    return this->free_threads;
}

float InnerScheduler::get_resources(){
    float resources = this->resources;
    return resources;
}

float InnerScheduler::get_resources_unsafe(){
    return this->resources;
}
