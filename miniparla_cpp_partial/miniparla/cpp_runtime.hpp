#pragma once

#include <vector>
#include <string>
#include <iostream>
#include <thread>
#include <mutex>
#include <atomic>

//Python Callbacks
typedef void (*callerfunc)(void* f, void* task);
typedef void (*stopfunc)(void* f);


void launch_task_callback(callerfunc func, void* f, void* arg);

class InnerScheduler;

//Runtime Classes

class InnerTask {
    public:
        //Unique ID of the task (dictionary key in python runtime)
        long id = 0;
        //Task Status
        bool complete = false;
        //Pointer to the python object that represents the task
        void* task = NULL;
        //Task Resources
        float vcus = 0.0;

        std::mutex m;

        //Task dependencies
        std::vector<InnerTask*> dependencies = std::vector<InnerTask*>();
        std::atomic<int> num_deps = 0;

        //Task dependents
        std::vector<InnerTask*> dependents = std::vector<InnerTask*>();

        InnerTask();
        InnerTask(long id, void* task, float vcus);

        void set_task(void* task);

        void add_dependency_unsafe(InnerTask* task);
        void add_dependency(InnerTask* task);
        void add_dependencies(std::vector<InnerTask*> task_list);
        void clear_dependencies();

        bool add_dependent(InnerTask* task);
        void notify_dependents(InnerScheduler* scheduler);
        bool notify();

        bool blocked_unsafe();
        bool blocked();

        int get_num_deps();

};

class InnerScheduler {

    public:
        //Task Ready Queue
        std::vector<InnerTask*> ready_queue;
        std::mutex ready_queue_mutex;

        //Resources (vcus)
        std::atomic<float> resources;
        std::mutex resources_mutex;

        //Active Task Count
        std::atomic<int> active_tasks;
        std::mutex active_tasks_mutex;

        //Running Task Count
        std::atomic<int> running_tasks;
        std::mutex running_tasks_mutex;

        //Free Thread Count
        std::atomic<int> free_threads;
        std::mutex free_threads_mutex;

        std::mutex launching_phase_mutex; //mutex for launching phase

        //Simplify model
        // Assume only a single task launching phase can run at a time
        //  - This means the only thing that removes a thread from the pool is a critical section

        // Assume the launching phase updates and releases resources
        //  - This means the only thing that decreases resources is a critical section

        // Places that the ready queue is increased:
        //  - When a task is completed, it notifies its dependents which may be added
        //  - When a task is spawned, it may be added

        // Places that the ready queue is decreased:
        //  - When a task is launched, it is removed from the ready queue

        // Dependencies/Dependents:
        // - When a task is spawned, adds dependencies and dependents
        // - When a task is completed, notifies dependents (decreases)

        // Unfinished Dependency Count: 
        // - When a task is spawned, adds dependencies to itself
        // - When a task is continued, adds dependencies to itself
        // - (no data movement in this model)
        // - When a dependency completes, decreases count

        //Termination Flag
        bool should_run = 1;

        callerfunc call;
        stopfunc py_stop;
        void* func;

        InnerScheduler();
        InnerScheduler(callerfunc func, float resources, int nthreads);

        void set_python_callback(callerfunc call, stopfunc stop, void* func);
        void set_nthreads(int nthreads);
        void set_resources(float resources);

        void enqueue_task(InnerTask* task);
        void enqueue_task_unsafe(InnerTask* task);

        InnerTask* dequeue_task();
        InnerTask* dequeue_task_unsafe();

        int get_ready_queue_size();
        int get_ready_queue_size_unsafe();

        void run_scheduler();
        bool run_launcher();
        void launch_task(InnerTask* task);

        void run();
        void stop();

        void incr_running_tasks();
        void decr_running_tasks();
        int get_running_tasks();
        int get_running_tasks_unsafe();

        void incr_active_tasks();
        bool decr_active_tasks();
        int get_active_tasks();
        int get_active_tasks_unsafe();

        void incr_free_threads();
        void decr_free_threads();
        int get_free_threads();
        int get_free_threads_unsafe();

        void incr_resources(float vcus);
        void incr_resources_unsafe(float vcus);
        void decr_resources(float vcus);
        void decr_resources_unsafe(float vcus);
        float get_resources();
        float get_resources_unsafe();
};

